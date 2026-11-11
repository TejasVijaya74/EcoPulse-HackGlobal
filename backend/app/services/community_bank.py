import json
import math
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from app.models import CreditTransaction, SimulationRecord


def _as_nonnegative(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if not math.isfinite(result) or result < 0:
        return None
    return result


def allocate_community_contribution(
    contribution_kwh: float,
    credit_rate: float,
    household_count: int,
) -> list[dict[str, float | str]]:
    if (
        not math.isfinite(contribution_kwh)
        or contribution_kwh <= 0
        or not math.isfinite(credit_rate)
        or credit_rate < 0
        or household_count <= 0
    ):
        return []

    total_energy = Decimal(str(contribution_kwh)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_credits = (total_energy * Decimal(str(credit_rate))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    energy_share = (total_energy / household_count).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )
    credit_share = int(total_credits * 100) // household_count
    credit_remainder = int(total_credits * 100) % household_count

    allocations = []
    allocated_energy = Decimal("0")
    for index in range(household_count):
        energy = (
            total_energy - allocated_energy
            if index == household_count - 1
            else energy_share
        )
        allocated_energy += energy
        credits_cents = credit_share + (1 if index < credit_remainder else 0)
        allocations.append(
            {
                "household_id": f"HH-{index + 1:03d}",
                "energy_kwh": float(energy),
                "credits": credits_cents / 100,
            }
        )
    return allocations


def validate_contribution_transactions(
    rows: list[CreditTransaction],
    simulations: dict[int, SimulationRecord],
) -> tuple[list[CreditTransaction], int]:
    grouped: dict[int, list[CreditTransaction]] = defaultdict(list)
    rejected_count = 0
    for row in rows:
        if row.simulation_id is None:
            rejected_count += 1
        else:
            grouped[row.simulation_id].append(row)

    accepted: list[CreditTransaction] = []
    for simulation_id, transactions in grouped.items():
        record = simulations.get(simulation_id)
        if record is None:
            rejected_count += len(transactions)
            continue
        try:
            result = json.loads(record.result_json)
            metrics = result["metrics"]
            parameters = result["parameters"]
            contribution = _as_nonnegative(metrics.get("community_contribution_kwh"))
            total_credits = _as_nonnegative(metrics.get("community_credits"))
            credit_rate = _as_nonnegative(parameters.get("credit_rate"))
            household_count = parameters.get("households")
        except (KeyError, TypeError, json.JSONDecodeError):
            rejected_count += len(transactions)
            continue

        valid = (
            contribution is not None
            and total_credits is not None
            and credit_rate is not None
            and isinstance(household_count, int)
            and not isinstance(household_count, bool)
            and household_count > 0
            and len(transactions) == household_count
        )
        expected_households = (
            {f"HH-{index:03d}" for index in range(1, household_count + 1)}
            if isinstance(household_count, int) and not isinstance(household_count, bool)
            else set()
        )
        household_ids = set()
        energy_total = credits_total = 0.0
        for row in transactions:
            energy = _as_nonnegative(row.energy_kwh)
            credits = _as_nonnegative(row.credits)
            if (
                row.transaction_type != "community_contribution"
                or row.household_id not in expected_households
                or row.household_id in household_ids
                or energy is None
                or energy <= 0
                or credits is None
                or credit_rate is None
                or abs(credits - energy * credit_rate) > 0.02
            ):
                valid = False
                break
            household_ids.add(row.household_id)
            energy_total += energy
            credits_total += credits

        if (
            valid
            and household_ids == expected_households
            and abs(energy_total - contribution) <= 0.00001
            and abs(credits_total - total_credits) <= 0.02
        ):
            accepted.extend(transactions)
        else:
            rejected_count += len(transactions)

    accepted.sort(key=lambda row: row.timestamp, reverse=True)
    return accepted, rejected_count
