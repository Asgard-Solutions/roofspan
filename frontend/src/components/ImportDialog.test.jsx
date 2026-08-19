import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ImportDialog from "./ImportDialog";

// Mock the api client + toasts so we can drive the import job lifecycle deterministically.
jest.mock("@/lib/api", () => ({
  api: { post: jest.fn(), get: jest.fn() },
  apiError: (e) => String(e),
}));
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

import { api } from "@/lib/api";
import { toast } from "sonner";

const TERRITORY = { id: "fa3b994c-01bc-48b7-b737-71bccd248005", name: "73010", zip_code: "73010" };

const PREVIEW = { estimated_properties: 7570, estimated_requests: 8, mode: "rentcast", note: "ok", sample: [] };

function mockJob(overrides = {}) {
  return {
    id: "job1", status: "completed", total: 7570, processed: 7570,
    created_count: 7570, updated_count: 0, skipped_count: 0, error: null,
    ...overrides,
  };
}

// api.post: 1st call = preview, 2nd call = start import (returns {id}).
function wirePost() {
  api.post
    .mockResolvedValueOnce({ data: PREVIEW })     // /import/preview
    .mockResolvedValueOnce({ data: { id: "job1" } }); // /import
}

async function runToConfirm(user) {
  await user.click(screen.getByTestId("import-preview-button"));
  const confirm = await screen.findByTestId("import-confirm-button");
  await user.click(confirm);
}

beforeEach(() => {
  api.post.mockReset();
  api.get.mockReset();
  toast.success.mockReset();
  toast.error.mockReset();
});

describe("ImportDialog — import-complete refresh contract", () => {
  test("successful completion invokes onComplete EXACTLY once and shows accurate counts", async () => {
    const user = userEvent.setup();
    wirePost();
    api.get.mockResolvedValue({ data: mockJob() }); // every poll + final read returns completed
    const onComplete = jest.fn();

    render(<ImportDialog open territory={TERRITORY} onOpenChange={() => {}} onComplete={onComplete} />);
    await runToConfirm(user);

    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1), { timeout: 4000 });

    // Result copy: processed / added / updated / skipped (not the misleading "+0 new").
    const result = await screen.findByTestId("import-result");
    expect(result).toHaveTextContent("Completed");
    expect(screen.getByTestId("import-processed")).toHaveTextContent("7,570");
    expect(screen.getByTestId("import-added")).toHaveTextContent("7,570");
    expect(screen.getByTestId("import-updated")).toHaveTextContent("0");
    expect(screen.getByTestId("import-skipped")).toHaveTextContent("0");
    expect(result).not.toHaveTextContent("+0 new");
  }, 10000);

  test("repeat import shows updated_count (not a misleading '+0 new')", async () => {
    const user = userEvent.setup();
    wirePost();
    api.get.mockResolvedValue({ data: mockJob({ created_count: 0, updated_count: 7570 }) });
    const onComplete = jest.fn();

    render(<ImportDialog open territory={TERRITORY} onOpenChange={() => {}} onComplete={onComplete} />);
    await runToConfirm(user);

    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1), { timeout: 4000 });
    expect(screen.getByTestId("import-added")).toHaveTextContent("0");
    expect(screen.getByTestId("import-updated")).toHaveTextContent("7,570");
    expect(screen.getByTestId("import-result")).not.toHaveTextContent("+0 new");
  }, 10000);

  test("onComplete is NOT fired for a failed job", async () => {
    const user = userEvent.setup();
    wirePost();
    api.get.mockResolvedValue({ data: mockJob({ status: "failed", error: "boom" }) });
    const onComplete = jest.fn();

    render(<ImportDialog open territory={TERRITORY} onOpenChange={() => {}} onComplete={onComplete} />);
    await runToConfirm(user);

    await waitFor(() => expect(toast.error).toHaveBeenCalled(), { timeout: 4000 });
    expect(onComplete).not.toHaveBeenCalled();
  }, 10000);

  test("onComplete is NOT fired while the job is still in-progress (no duplicate polling refresh)", async () => {
    const user = userEvent.setup();
    wirePost();
    // Poll returns 'running' several times before completing -> onComplete must still fire ONCE.
    api.get
      .mockResolvedValueOnce({ data: mockJob({ status: "running", processed: 100 }) })
      .mockResolvedValueOnce({ data: mockJob({ status: "running", processed: 4000 }) })
      .mockResolvedValue({ data: mockJob() });
    const onComplete = jest.fn();

    render(<ImportDialog open territory={TERRITORY} onOpenChange={() => {}} onComplete={onComplete} />);
    await runToConfirm(user);

    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1), { timeout: 6000 });
    // exactly once even though polling ran multiple iterations
    expect(onComplete).toHaveBeenCalledTimes(1);
  }, 12000);
});
