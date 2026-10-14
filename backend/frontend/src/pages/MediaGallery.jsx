import { useCallback, useState } from "react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { PageHeader } from "../components/Layout";
import { Loading, ErrorState } from "../components/StateViews";

export default function MediaGallery() {
  const samplesFn = useCallback(() => api.listMediaSamples(), []);
  const samples = useApi(samplesFn, []);

  const [selected, setSelected] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);

  const loadSample = (s) => {
    if (!s) return;
    setPreviewUrl(`/media/samples/${encodeURIComponent(s.filename)}`);
    setSelected(s);
  };

  return (
    <>
      <PageHeader
        title="Media Gallery"
        subtitle="Drone frames and satellite thumbnails to run through aerial flood detection"
      />

      <div className="media-layout">
        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Bundled sample frames</h2>
            <span className="panel__hint">{samples.data?.length ?? 0} samples</span>
          </div>

          {samples.loading && !samples.data ? (
            <Loading label="Loading samples…" />
          ) : samples.error && !samples.data ? (
            <ErrorState error={samples.error} onRetry={samples.refetch} label="Could not load samples" />
          ) : !samples.data?.length ? (
            <div className="muted">No bundled samples available. Upload your own to test detection.</div>
          ) : (
            <div className="media-grid">
              {samples.data.map((s) => (
                <button
                  key={s.filename}
                  type="button"
                  className="media-card"
                  onClick={() => loadSample(s)}
                >
                  <span className="media-card__thumb">
                    {previewUrl === s.path ? (
                      <img src={`/media/samples/${encodeURIComponent(s.filename)}`} alt="" />
                    ) : (
                      <span className="media-card__placeholder">{s.filename}</span>
                    )}
                  </span>
                  <span className="media-card__name">{s.filename}</span>
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="panel panel--wide">
          <div className="panel__head">
            <h2 className="panel__title">Preview</h2>
            {selected && <span className="tag">{selected.filename}</span>}
          </div>

          <div className="media-preview">
            {previewUrl ? (
              <img src={previewUrl} alt="Selected sample" className="media-preview__img" />
            ) : (
              <div className="media-preview__empty">Select a sample frame</div>
            )}
          </div>

          {selected && (
            <div className="media-detail">
              <div className="field">
                <div className="field__label">Filename</div>
                <div className="field__value">{selected.filename}</div>
              </div>
              <div className="field">
                <div className="field__label">Size</div>
                <div className="field__value">{Math.round(selected.size / 1024)} KB</div>
              </div>
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => {
                  if (window.confirm("Run aerial flood detection on this sample?")) {
                    fetch(`/media/samples/${encodeURIComponent(selected.filename)}`, { method: "GET" })
                      .then((r) => r.blob())
                      .then((blob) => new FileReader().readAsDataURL(blob))
                      .then((text) => {
                        const input = document.createElement("input");
                        input.type = "hidden";
                        input.name = "image_base64";
                        input.value = text;
                        document.getElementById("aerial-form")?.appendChild(input);
                        document.getElementById("aerial-run")?.click();
                      });
                  }
                }}
              >
                Analyze sample
              </button>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
