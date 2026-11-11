from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Scenario = Literal[
    "normal",
    "heatwave",
    "heavy_cloud",
    "high_demand",
    "grid_outage",
    "low_solar",
    "evening_peak",
    "solar_surplus",
    "storage_constraints",
]

ResearchTopic = Literal[
    "solar",
    "storage",
    "grid",
    "india_policy",
    "community_energy",
    "climate_risks",
    "renewables",
]


class SimulationParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: Scenario = "normal"
    households: int = Field(default=60, ge=1, le=5000)
    solar_capacity_kw: float = Field(default=180, ge=0, le=100000)
    storage_capacity_kwh: float = Field(default=320, ge=0, le=100000)
    initial_storage_percent: float = Field(default=55, ge=0, le=100)
    grid_import_limit_kw: float = Field(default=250, ge=0, le=100000)
    grid_export_limit_kw: float = Field(default=120, ge=0, le=100000)
    cloud_cover: float = Field(default=0.35, ge=0, le=1)
    temperature_c: float = Field(default=22, ge=-40, le=60)
    demand_multiplier: float = Field(default=1, gt=0, le=5)
    grid_available: bool = True
    duration_hours: int = Field(default=48, ge=24, le=168)
    random_seed: int = Field(default=42, ge=0, le=2_147_483_647)


class DemoSimulationParameters(SimulationParameters):
    households: int = Field(default=60, ge=1, le=250)
    solar_capacity_kw: float = Field(default=180, ge=0, le=500)
    storage_capacity_kwh: float = Field(default=320, ge=0, le=1000)
    grid_import_limit_kw: float = Field(default=250, ge=0, le=500)
    grid_export_limit_kw: float = Field(default=120, ge=0, le=500)
    duration_hours: int = Field(default=48, ge=24, le=48)


class ConfigurationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    households: int = Field(ge=1, le=5000)
    solar_capacity_kw: float = Field(ge=0, le=100000)
    storage_capacity_kwh: float = Field(ge=0, le=100000)
    initial_storage_percent: float = Field(ge=0, le=100)
    grid_import_limit_kw: float = Field(ge=0, le=100000)
    grid_export_limit_kw: float = Field(ge=0, le=100000)
    cloud_cover: float = Field(ge=0, le=1)
    temperature_c: float = Field(ge=-40, le=60)
    demand_multiplier: float = Field(gt=0, le=5)
    grid_available: bool
    charging_efficiency: float = Field(gt=0, le=1)
    discharging_efficiency: float = Field(gt=0, le=1)
    self_discharge_per_hour: float = Field(ge=0, le=0.1)
    max_charge_kw: float = Field(ge=0, le=100000)
    max_discharge_kw: float = Field(ge=0, le=100000)
    credit_rate: float = Field(ge=0, le=10000)
    random_seed: int = Field(ge=0, le=2_147_483_647)


class TrainingResponse(BaseModel):
    trained_at: str
    samples: int
    metrics: dict[str, dict[str, float]]


class AdvisorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    research_topic: ResearchTopic | None = None

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        question = value.strip()
        if not question:
            raise ValueError("Question must not be blank.")
        return question
