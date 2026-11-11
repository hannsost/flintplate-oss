"use client";

import { useCallback, useState } from "react";

interface CVDropzoneProps {
  onUpload: (file: File) => Promise<void>;
  currentFilename?: string | null;
  disabled?: boolean;
}

const ACCEPTED = ["application/pdf", "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document"];
const MAX_MB = 10;

export function CVDropzone({ onUpload, currentFilename, disabled }: CVDropzoneProps) {
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const handleFile = useCallback(
    async (file: File) => {
      setError(null);
      if (!ACCEPTED.includes(file.type)) {
        setError("Nur PDF, DOC oder DOCX erlaubt.");
        return;
      }
      if (file.size > MAX_MB * 1024 * 1024) {
        setError(`Datei zu groß – max. ${MAX_MB} MB erlaubt.`);
        return;
      }
      setUploading(true);
      try {
        await onUpload(file);
      } catch {
        setError("Upload fehlgeschlagen. Bitte versuche es erneut.");
      } finally {
        setUploading(false);
      }
    },
    [onUpload],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    e.target.value = "";
  };

  return (
    <div className="space-y-2">
      <label
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={[
          "flex flex-col items-center justify-center w-full rounded-xl border-2 border-dashed px-6 py-10 cursor-pointer transition-colors",
          dragging
            ? "border-blue-500 bg-blue-50"
            : "border-gray-300 bg-gray-50 hover:border-blue-400 hover:bg-blue-50",
          disabled ? "opacity-50 pointer-events-none" : "",
        ].join(" ")}
      >
        <input
          type="file"
          accept=".pdf,.doc,.docx"
          className="sr-only"
          onChange={onInputChange}
          disabled={disabled || uploading}
        />

        {uploading ? (
          <p className="text-sm text-blue-600 font-medium animate-pulse">
            Wird hochgeladen und analysiert…
          </p>
        ) : (
          <>
            <svg
              className="mb-3 h-10 w-10 text-gray-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M12 16v-8m0 0-3 3m3-3 3 3M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1"
              />
            </svg>
            <p className="text-sm text-gray-600">
              <span className="font-semibold text-blue-600">Datei auswählen</span>
              {" "}oder hierher ziehen
            </p>
            <p className="mt-1 text-xs text-gray-400">PDF, DOC, DOCX – max. 10 MB</p>
          </>
        )}
      </label>

      {currentFilename && !uploading && (
        <p className="text-xs text-gray-500">
          Aktuell:{" "}
          <span className="font-medium text-gray-700">{currentFilename}</span>
        </p>
      )}

      {error && (
        <p className="text-xs text-red-600">{error}</p>
      )}
    </div>
  );
}
