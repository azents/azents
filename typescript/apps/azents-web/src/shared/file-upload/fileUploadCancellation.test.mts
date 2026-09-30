import assert from "node:assert/strict";
import test from "node:test";
import {
  createFileUploadCancellationCoordinator,
  type FileUploadCancellationCoordinator,
} from "./fileUploadCancellation.ts";

interface Operation {
  id: string;
}

void test("skips a queued file from a captured upload snapshot after cancellation", () => {
  const coordinator = createFileUploadCancellationCoordinator<Operation>(
    (): void => {},
  );
  const uploadSnapshot = ["active", "queued"];
  const startedFileIds: string[] = [];

  for (const fileId of uploadSnapshot) {
    if (coordinator.isCancelled(fileId)) {
      continue;
    }
    startedFileIds.push(fileId);
    if (fileId === "active") {
      coordinator.cancelFile("queued");
    }
  }

  assert.deepEqual(startedFileIds, ["active"]);
});

void test("unmount-style cancellation marks all pending IDs before cancelling active operations", () => {
  const cancelledOperationIds: string[] = [];
  let queuedWasCancelledWhenActiveTaskCancelled = false;
  let activeWasCancelledWhenActiveTaskCancelled = false;
  const coordinator: FileUploadCancellationCoordinator<Operation> =
    createFileUploadCancellationCoordinator<Operation>(
      (operation: Operation): void => {
        queuedWasCancelledWhenActiveTaskCancelled =
          coordinator.isCancelled("queued");
        activeWasCancelledWhenActiveTaskCancelled = coordinator.isCancelled(
          operation.id,
        );
        cancelledOperationIds.push(operation.id);
      },
    );
  coordinator.registerOperation("active", { id: "active" });

  coordinator.cancelFiles(["queued", "active"]);

  assert.equal(coordinator.isCancelled("queued"), true);
  assert.equal(coordinator.isCancelled("active"), true);
  assert.equal(queuedWasCancelledWhenActiveTaskCancelled, true);
  assert.equal(activeWasCancelledWhenActiveTaskCancelled, true);
  assert.deepEqual(cancelledOperationIds, ["active"]);
});
