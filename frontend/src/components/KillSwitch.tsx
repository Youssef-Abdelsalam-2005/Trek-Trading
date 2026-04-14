import { useCallback, useEffect, useRef, useState } from "react";
import { useKillSwitch } from "../hooks/useKillSwitch";

export default function KillSwitch() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const { state, trigger, reset } = useKillSwitch();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  const openDialog = useCallback(() => {
    reset();
    setDialogOpen(true);
  }, [reset]);

  const closeDialog = useCallback(() => {
    setDialogOpen(false);
  }, []);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (dialogOpen && !dialog.open) {
      dialog.showModal();
      cancelRef.current?.focus();
    } else if (!dialogOpen && dialog.open) {
      dialog.close();
    }
  }, [dialogOpen]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const handleClose = () => setDialogOpen(false);
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, []);

  const handleConfirm = useCallback(() => {
    trigger();
  }, [trigger]);

  return (
    <>
      <button
        type="button"
        className="kill-btn"
        onClick={openDialog}
        aria-label="Kill all live trading"
      >
        KILL ALL
      </button>

      <dialog ref={dialogRef} className="kill-dialog" aria-labelledby="kill-dialog-title">
        <div className="kill-dialog__content">
          <h2 id="kill-dialog-title" className="kill-dialog__title">
            Kill All Live Trading
          </h2>

          {state.status === "idle" && (
            <p className="kill-dialog__body">
              This will immediately stop <strong>all live, paper-trading, and halted strategies</strong>.
              In-flight transactions will complete but no new trades will be submitted.
              This action cannot be easily undone.
            </p>
          )}

          {state.status === "pending" && (
            <p className="kill-dialog__body kill-dialog__body--pending" aria-live="polite">
              Killing all strategies...
            </p>
          )}

          {state.status === "success" && (
            <div className="kill-dialog__body kill-dialog__body--success" aria-live="polite">
              <p>
                <strong>{state.data.strategies_affected}</strong> strateg{state.data.strategies_affected === 1 ? "y" : "ies"} killed.
              </p>
              <p>All trading has been halted.</p>
            </div>
          )}

          {state.status === "error" && (
            <div className="kill-dialog__body kill-dialog__body--error" role="alert">
              <p>Failed to activate kill switch.</p>
              <p className="kill-dialog__error-detail">{state.message}</p>
            </div>
          )}

          <div className="kill-dialog__actions">
            {(state.status === "idle" || state.status === "error") && (
              <>
                <button
                  ref={cancelRef}
                  type="button"
                  className="kill-dialog__cancel"
                  onClick={closeDialog}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="kill-dialog__confirm"
                  onClick={handleConfirm}
                >
                  Confirm Kill
                </button>
              </>
            )}
            {state.status === "pending" && (
              <button type="button" className="kill-dialog__cancel" disabled>
                Please wait...
              </button>
            )}
            {state.status === "success" && (
              <button type="button" className="kill-dialog__cancel" onClick={closeDialog}>
                Close
              </button>
            )}
          </div>
        </div>
      </dialog>
    </>
  );
}
