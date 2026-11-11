import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";

vi.mock("../hooks/useLiveTelemetry", () => ({
  default: () => ({ telemetry: null, connection: "offline" }),
}));

vi.mock("../pages/Overview", () => ({ default: () => <div /> }));

vi.mock("../services/api", async (importOriginal) => ({
  ...(await importOriginal()),
  errorMessage: (error) => error.response?.data?.detail || error.message,
  getApiAccessToken: vi.fn(() => "existing-valid-token"),
  getConfig: vi.fn().mockResolvedValue({}),
  getCredits: vi.fn().mockResolvedValue({ household_credits: [], transactions: [] }),
  getDashboard: vi.fn().mockResolvedValue({}),
  getForecast: vi.fn().mockResolvedValue({}),
  runSimulation: vi.fn(),
  setApiAccessToken: vi.fn(),
  validateApiAccessToken: vi.fn().mockResolvedValue({}),
}));

import { setApiAccessToken, validateApiAccessToken } from "../services/api";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function openAccessDialog(user) {
  await user.click(screen.getByRole("button", { name: "Community Energy Bank" }));
  await user.click(screen.getByText("Access set"));
}

describe("Set Access dialog", () => {
  it("submits a validated token and does not store it before validation", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openAccessDialog(user);
    const tokenInput = screen.getByLabelText("Backend bearer token");
    fireEvent.change(tokenInput, { target: { value: "candidate-token" } });
    await user.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(setApiAccessToken).toHaveBeenCalledWith("candidate-token"));
    expect(validateApiAccessToken).toHaveBeenCalledWith("candidate-token");
    expect(await screen.findByText("Access token verified.")).toBeTruthy();
  });

  it("submits when Enter is pressed in the token input", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openAccessDialog(user);
    const tokenInput = screen.getByLabelText("Backend bearer token");
    fireEvent.change(tokenInput, { target: { value: "enter-submitted-token" } });
    tokenInput.focus();
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(validateApiAccessToken).toHaveBeenCalledWith("enter-submitted-token"),
    );
    expect(setApiAccessToken).toHaveBeenCalledWith("enter-submitted-token");
  });

  it("disables submission while the candidate token is being validated", async () => {
    const user = userEvent.setup();
    let finishValidation;
    validateApiAccessToken.mockImplementationOnce(
      () => new Promise((resolve) => { finishValidation = resolve; }),
    );
    render(<App />);
    await openAccessDialog(user);
    const tokenInput = screen.getByLabelText("Backend bearer token");
    fireEvent.change(tokenInput, { target: { value: "pending-token" } });
    await user.click(screen.getByRole("button", { name: "Submit" }));

    expect(screen.getByRole("button", { name: "Validating…" }).disabled).toBe(true);
    finishValidation({});
    await waitFor(() => expect(setApiAccessToken).toHaveBeenCalledWith("pending-token"));
  });

  it("closes without clearing the configured token", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openAccessDialog(user);
    const details = screen.getByText("Access set").closest("details");
    await user.click(screen.getByRole("button", { name: "Close access dialog" }));

    expect(details.open).toBe(false);
    expect(setApiAccessToken).not.toHaveBeenCalled();
  });

  it("shows invalid-token feedback and keeps the existing token", async () => {
    const user = userEvent.setup();
    validateApiAccessToken.mockRejectedValueOnce({
      response: { data: { detail: "A valid bearer token is required." } },
    });
    render(<App />);
    await openAccessDialog(user);
    const tokenInput = screen.getByLabelText("Backend bearer token");
    fireEvent.change(tokenInput, { target: { value: "invalid-token" } });
    await user.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByText("A valid bearer token is required.")).toBeTruthy();
    expect(setApiAccessToken).not.toHaveBeenCalled();
  });
});
