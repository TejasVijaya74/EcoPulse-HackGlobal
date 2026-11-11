import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Credits from "../pages/Credits";

vi.mock("../services/api", async (importOriginal) => ({
  ...(await importOriginal()),
  errorMessage: (error) => error.response?.data?.detail || error.message,
  getCredits: vi.fn(),
  resetCommunityBank: vi.fn(),
}));

import { getCredits, resetCommunityBank } from "../services/api";

const credits = {
  total_credits: 0,
  household_credits: [],
  transactions: [],
  energy_bank: {
    capacity_kwh: 100,
    stored_energy_kwh: 50,
    state_of_charge_percent: 50,
    energy_discharged_kwh: 0,
    community_contribution_kwh: 0,
  },
};

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close() {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Community Energy Bank reset", () => {
  it("requires confirmation and does not reset when cancelled", async () => {
    const user = userEvent.setup();
    render(<Credits credits={credits} onCreditsUpdated={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Reset Data" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog.open).toBe(true);
    expect(dialog.textContent).toContain("associated simulated transaction records");

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(dialog.open).toBe(false);
    expect(resetCommunityBank).not.toHaveBeenCalled();
  });

  it("resets, reloads the bank, and displays success feedback after confirmation", async () => {
    const user = userEvent.setup();
    const onCreditsUpdated = vi.fn();
    const refreshedCredits = { ...credits, total_credits: 0 };
    resetCommunityBank.mockResolvedValue({});
    getCredits.mockResolvedValue(refreshedCredits);
    render(<Credits credits={credits} onCreditsUpdated={onCreditsUpdated} />);

    await user.click(screen.getByRole("button", { name: "Reset Data" }));
    await user.click(screen.getByRole("button", { name: "Confirm Reset" }));

    await waitFor(() => expect(resetCommunityBank).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(getCredits).toHaveBeenCalledTimes(1));
    expect(onCreditsUpdated).toHaveBeenCalledWith(refreshedCredits);
    expect((await screen.findByRole("status")).textContent).toContain(
      "Community Energy Bank data was reset.",
    );
  });

  it("keeps the confirmation open and reports a reset failure", async () => {
    const user = userEvent.setup();
    resetCommunityBank.mockRejectedValueOnce({
      response: { data: { detail: "Community Energy Bank data could not be reset." } },
    });
    render(<Credits credits={credits} onCreditsUpdated={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Reset Data" }));
    await user.click(screen.getByRole("button", { name: "Confirm Reset" }));

    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByRole("alert")).toBeTruthy();
    expect(dialog.open).toBe(true);
    expect(getCredits).not.toHaveBeenCalled();
  });
});
