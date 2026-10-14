import { useRef, useState, useEffect } from "react";
import { api } from "../api/client";

export default function ExportDropdown() {
  const [open, setOpen] = useState(false);
  const [exporting, setExporting] = useState(null);
  const [error, setError] = useState(null);
  const dropdownRef = useRef(null);

  useEffect(() => {
    function handleClickOutside(event) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const downloadBlob = (blob, filename) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleExport = async (format) => {
    setError(null);
    setExporting(format);
    try {
      let blob;
      let filename;
      if (format === "geojson") {
        blob = await api.exportGeoJSON(true);
        filename = "resqmap-zones.geojson";
      } else if (format === "pdf") {
        blob = await api.exportPDF();
        filename = "resqmap-report.pdf";
      } else if (format === "png") {
        blob = await api.exportPNG();
        filename = "resqmap-map.png";
      }
      downloadBlob(blob, filename);
      setOpen(false);
    } catch (err) {
      setError(err.message || `Failed to export ${format.toUpperCase()}`);
    } finally {
      setExporting(null);
    }
  };

  const options = [
    {
      format: "geojson",
      label: "GeoJSON",
      desc: "Priority zones + GIS layers",
      icon: "⬢",
    },
    {
      format: "pdf",
      label: "PDF Report",
      desc: "Formatted table with summary",
      icon: "📄",
    },
    {
      format: "png",
      label: "PNG Map",
      desc: "Visual snapshot of zones",
      icon: "🖼",
    },
  ];

  return (
    <div className="export-dropdown" ref={dropdownRef}>
      <button
        type="button"
        className={`btn btn--secondary ${open ? "is-open" : ""}`}
        onClick={() => setOpen(!open)}
        disabled={exporting !== null}
        aria-expanded={open}
        aria-haspopup="true"
      >
        <span>⤓ Export</span>
        {exporting && <span className="btn__spinner" />}
      </button>

      {open && (
        <div className="export-dropdown__menu" role="menu">
          {options.map((opt) => (
            <button
              key={opt.format}
              type="button"
              className="export-dropdown__item"
              role="menuitem"
              onClick={() => handleExport(opt.format)}
              disabled={exporting !== null}
            >
              <span className="export-dropdown__icon">{opt.icon}</span>
              <div className="export-dropdown__text">
                <span className="export-dropdown__label">{opt.label}</span>
                <span className="export-dropdown__desc">{opt.desc}</span>
              </div>
              {exporting === opt.format && <span className="export-dropdown__loading">Exporting…</span>}
            </button>
          ))}
          {error && (
            <div className="export-dropdown__error" role="alert">
              {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}