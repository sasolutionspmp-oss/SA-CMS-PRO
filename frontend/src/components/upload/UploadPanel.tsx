import clsx from "clsx";
import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Loader2, Trash2, UploadCloud, X } from "lucide-react";

export type UploadStatus = "queued" | "uploading" | "success" | "error";

export interface UploadItem {
  id: string;
  fileName: string;
  size: number;
  status: UploadStatus;
  progress: number;
  startedAt?: number;
  completedAt?: number;
}

export interface UploadPanelProps {
  className?: string;
}

interface ActiveUploadController {
  id: string;
  cancel: () => void;
}

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size <= 0) {
    return '0 B';
  }
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = size;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const digits = value >= 10 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[unitIndex]}`;
}

function statusLabel(status: UploadStatus): string {
  switch (status) {
    case 'queued':
      return 'Queued';
    case 'uploading':
      return 'Uploading';
    case 'success':
      return 'Uploaded';
    case 'error':
      return 'Cancelled';
    default:
      return status;
  }
}

export function UploadPanel({ className, projectId }: UploadPanelProps): JSX.Element {
  const [items, setItems] = useState<UploadItem[]>([]);
  const activeRef = useRef<ActiveUploadController | null>(null);

  useEffect(() => {
    if (activeRef.current) {
      const activeId = activeRef.current.id;
      const stillUploading = items.some((item) => item.id === activeId && item.status === 'uploading');
      if (stillUploading) {
        return;
      }
      activeRef.current = null;
    }

    const next = items.find((item) => item.status === 'queued');
    if (!next) {
      return;
    }

    const uploadId = next.id;
    setItems((prev) =>
      prev.map((item) =>
        item.id === uploadId
          ? {
              ...item,
              status: 'uploading',
              startedAt: Date.now(),
              progress: Math.max(item.progress, 5),
            }
          : item,
      ),
    );

    let progress = 5;
    const interval = window.setInterval(() => {
      progress = Math.min(progress + Math.random() * 12, 95);
      setItems((prev) => prev.map((item) => (item.id === uploadId ? { ...item, progress } : item))); 
    }, 180);

    const completion = window.setTimeout(() => {
      window.clearInterval(interval);
      setItems((prev) =>
        prev.map((item) =>
          item.id === uploadId
            ? {
                ...item,
                status: 'success',
                progress: 100,
                completedAt: Date.now(),
              }
            : item,
        ),
      );
      activeRef.current = null;
    }, 2200 + Math.random() * 800);

    activeRef.current = {
      id: uploadId,
      cancel: () => {
        window.clearInterval(interval);
        window.clearTimeout(completion);
        setItems((prev) =>
          prev.map((item) =>
            item.id === uploadId
              ? {
                  ...item,
                  status: 'error',
                  progress: item.progress,
                  completedAt: Date.now(),
                }
              : item,
          ),
        );
        activeRef.current = null;
      },
    };
  }, [items]);

  useEffect(
    () => () => {
      if (activeRef.current) {
        activeRef.current.cancel();
      }
    },
    [],
  );

  const totalBytes = useMemo(() => items.reduce((acc, item) => acc + item.size, 0), [items]);
  const totalFiles = items.length;
  const completed = items.filter((item) => item.status === 'success').length;

  const handleFilesSelected = (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) {
      return;
    }

    const additions: UploadItem[] = Array.from(fileList).map((file) => ({
      id: `${Date.now()}-${file.name}-${Math.random().toString(16).slice(2)}`,
      fileName: file.name,
      size: file.size,
      status: 'queued',
      progress: 0,
    }));

    setItems((prev) => [...prev, ...additions]);
  };

  const handleClearCompleted = () => {
    setItems((prev) => prev.filter((item) => item.status !== 'success'));
  };

  const handleRemove = (id: string) => {
    const active = activeRef.current;
    if (active?.id === id) {
      active.cancel();
    }
    setItems((prev) => prev.filter((item) => item.id !== id));
  };

  const queueSummary = useMemo(() => {
    const uploading = items.find((item) => item.status === 'uploading');
    const queued = items.filter((item) => item.status === 'queued').length;
    return { uploading, queued };
  }, [items]);

  return (
    <section className={clsx('space-y-4', className)} aria-label="Upload bundle">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-text-primary">Upload bundle</h3>
          <p className="text-xs text-text-secondary">
            Queue design files for intake
            {projectId ? ` on project ${projectId}` : ''}; uploads simulate progress until backend wiring is complete.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {completed > 0 ? (
            <button
              type="button"
              onClick={handleClearCompleted}
              className="inline-flex items-center gap-2 rounded-full border border-border-subtle bg-surface px-3 py-1.5 text-xs font-medium text-text-secondary shadow-panel transition hover:bg-surface-muted"
            >
              <Trash2 className="h-3.5 w-3.5" /> Clear completed
            </button>
          ) : null}
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-border-subtle bg-surface px-3 py-1.5 text-xs font-semibold text-text-secondary shadow-panel transition hover:bg-surface-muted">
            <UploadCloud className="h-3.5 w-3.5" /> Add files
            <input
              type="file"
              multiple
              className="hidden"
              onChange={(event) => {
                handleFilesSelected(event.target.files);
                event.target.value = '';
              }}
            />
          </label>
        </div>
      </div>

      <div className="rounded-xl border border-border-subtle bg-surface-muted-soft p-4 shadow-panel space-y-3">
        <div className="flex flex-wrap items-center justify-between text-xs text-text-secondary">
          <span>
            {totalFiles} file{totalFiles === 1 ? '' : 's'} in queue
            {queueSummary.uploading ? ` · uploading ${queueSummary.uploading.fileName}` : ''}
            {queueSummary.queued ? ` · ${queueSummary.queued} waiting` : ''}
          </span>
          <span>{formatBytes(totalBytes)}</span>
        </div>
        <div className="space-y-2">
          {items.length === 0 ? (
            <div className="rounded-lg border border-border-subtle border-dashed bg-surface px-4 py-6 text-center text-sm text-text-secondary">
              Add files to start the upload queue.
            </div>
          ) : (
            items.map((item) => {
              const isUploading = item.status === 'uploading';
              const isSuccess = item.status === 'success';
              const isError = item.status === 'error';
              const statusClasses = clsx('text-xs font-semibold', {
                'text-success': isSuccess,
                'text-warning': item.status === 'queued' || isUploading,
                'text-danger': isError,
              });
              return (
                <div key={item.id} className="rounded-lg border border-border-subtle bg-surface px-3 py-2 shadow-panel">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-text-primary">{item.fileName}</p>
                      <div className="flex items-center gap-2 text-xs text-text-secondary">
                        <span>{formatBytes(item.size)}</span>
                        <span aria-hidden>·</span>
                        <span className={statusClasses}>{statusLabel(item.status)}</span>
                      </div>
                    </div>
                    <button
                      type="button"
                      className="rounded-full border border-border-subtle bg-surface px-2 py-1 text-xs text-text-tertiary shadow-panel transition hover:bg-surface-muted"
                      onClick={() => handleRemove(item.id)}
                      aria-label={`Remove ${item.fileName} from queue`}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <div className="mt-2 h-2 rounded-full bg-surface-inset">
                    <div
                      className={clsx('h-full rounded-full transition-all', {
                        'bg-accent': isUploading,
                        'bg-success': isSuccess,
                        'bg-warning': item.status === 'queued',
                        'bg-danger': isError,
                      })}
                      style={{ width: `${item.progress}%` }}
                    />
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </section>
  );
}
