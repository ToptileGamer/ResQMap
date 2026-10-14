from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from app.models import ExportRequest, ExportResponse, PriorityZonesResponse
from app.services.data_store import get_store
from app.services.gis_layer_service import layer
from app.scoring import compute_hazard_severity
from app.services.sensor_service import get_sensor_service

router = APIRouter(prefix="/export", tags=["export"])

GIS_LAYER_SUBS = {
    "rivers": "rivers",
    "elevation": "elevation",
    "population": "population_density",
}

def _build_priority_zones() -> list[dict[str, Any]]:
    store = get_store()
    zones = store.list_zones()
    sensor_service = get_sensor_service()

    stations = sensor_service.get_all_stations()
    readings = sensor_service.get_latest_readings()

    gis = {key: layer(sub) for key, sub in GIS_LAYER_SUBS.items()}

    zones_out: list[dict[str, Any]] = []
    for zone in zones:
        priority = compute_hazard_severity(
            zone,
            stations,
            readings,
            gis["rivers"],
            gis["elevation"],
            gis["population"],
            sensor_service_radius_km=4.0,
        )
        zones_out.append({
            "id": priority.id,
            "name": priority.name,
            "latitude": priority.latitude,
            "longitude": priority.longitude,
            "severity": priority.severity,
            "score": priority.score,
            "reasons": priority.reasons,
            "cv_flood_pct": priority.cv_flood_pct,
            "sensor_alerts": priority.sensor_alerts,
            "gis_risk_factors": priority.gis_risk_factors,
            "population_at_risk": priority.population_at_risk,
            "area_km2": priority.area_km2,
            "confidence": priority.confidence,
        })

    zones_out.sort(key=lambda item: item["score"], reverse=True)
    return zones_out


def _zones_to_geojson(zones: list[dict[str, Any]], include_gis_layers: bool = False) -> dict[str, Any]:
    features = []
    for zone in zones:
        properties = {
            "id": zone["id"],
            "name": zone["name"],
            "severity": zone["severity"],
            "score": zone["score"],
            "cv_flood_pct": zone["cv_flood_pct"],
            "sensor_alerts": zone["sensor_alerts"],
            "population_at_risk": zone["population_at_risk"],
            "area_km2": zone["area_km2"],
            "confidence": zone["confidence"],
            "reasons": zone["reasons"],
            "gis_risk_factors": zone["gis_risk_factors"],
        }
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [zone["longitude"], zone["latitude"]],
            },
            "properties": properties,
        })

    geojson = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_zones": len(zones),
            "source": "ResQMap AI",
        },
    }

    if include_gis_layers:
        gis_layers = {}
        for key, sub in GIS_LAYER_SUBS.items():
            gis_layers[key] = layer(sub)
        geojson["gis_layers"] = gis_layers

    return geojson


@router.post("", response_model=ExportResponse)
async def export_data(request: ExportRequest) -> ExportResponse:
    """Export detected zones in various formats.

    Supported formats:
    - geojson: GeoJSON FeatureCollection with priority zones and optional GIS layers
    - pdf: PDF report with priority zones table and map snapshot
    - png: PNG image snapshot of the priority zones map
    """
    zones = _build_priority_zones()

    if request.format == "geojson":
        geojson = _zones_to_geojson(zones, include_gis_layers=request.layers is not None)
        json_bytes = json.dumps(geojson, indent=2).encode("utf-8")
        return StreamingResponse(
            io.BytesIO(json_bytes),
            media_type="application/geo+json",
            headers={"Content-Disposition": 'attachment; filename="resqmap-zones.geojson"'},
        )

    elif request.format == "pdf":
        pdf_bytes = _generate_pdf_report(zones)
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="resqmap-report.pdf"'},
        )

    elif request.format == "png":
        png_bytes = _generate_png_map(zones)
        return StreamingResponse(
            io.BytesIO(png_bytes),
            media_type="image/png",
            headers={"Content-Disposition": 'attachment; filename="resqmap-map.png"'},
        )

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {request.format}")


@router.get("/risk")
async def export_risk(model: str = Query(default="ml"), rainfall_multiplier: float = Query(default=1.0), horizon_hours: int = Query(default=6)) -> Response:
    """Stage 3F: GeoJSON export of risk cells."""
    import json as _json
    from app.services.risk_service import risk_grid as _rg
    g = _rg(model, rainfall_multiplier, horizon_hours)
    return Response(content=_json.dumps(g["geojson"]).encode(), media_type="application/geo+json", headers={"Content-Disposition": 'attachment; filename="resqmap-risk.geojson"'})


@router.get("/predictions.csv")
async def export_predictions_csv(model: str = Query(default="ml"), rainfall_multiplier: float = Query(default=1.0), horizon_hours: int = Query(default=6)) -> Response:
    """Stage 3F: CSV ranked predictions."""
    import io as _io, csv as _csv
    from app.services.risk_service import predicted_zones as _pz
    pz = _pz(model, rainfall_multiplier, horizon_hours)
    out = _io.StringIO()
    w = _csv.writer(out)
    w.writerow(["zone_id", "zone_name", "probability", "confidence", "risk_level", "top_factors", "population_exposed", "reason"])
    for z in pz["zones"]:
        w.writerow([z["zone_id"], z["zone_name"], z["probability"], z["confidence"], z["risk_level"], "|".join(z["top_factors"]), z["population_exposed"], z["reason"]])
    return Response(content=out.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="predictions.csv"'})


@router.get("/risk-briefing")
async def export_risk_briefing(model: str = Query(default="ml")) -> Response:
    """Stage 3F: PDF briefing with heatmap metrics + model performance."""
    import io as _io
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from app.services.risk_service import risk_grid as _rg, predicted_zones as _pz
    from app.services.prediction_ml_engine import train as _train, backtest as _bt
    g = _rg(model, 1.0, 6)
    pz = _pz(model, 1.0, 6)
    m = _train()
    b = _bt(8)
    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [Paragraph("ResQMap Stage 3 — Risk Forecast Briefing (simulated prediction)", styles["Heading1"]), Spacer(1, 6),
             Paragraph(f"Model: {model} (default ml: RandomForest beats rule on ROC-AUC). Mean risk {g['summary']['mean_risk']}, high cells {g['summary']['high_cells']}, area at risk {g['summary']['area_at_risk_km2']} km2, people exposed {g['summary']['people_exposed']}.", styles["Normal"]), Spacer(1, 6),
             Paragraph(f"ML metrics: acc {m['accuracy']}, prec {m['precision']}, rec {m['recall']}, AUC {m['roc_auc']}, CM {m['confusion_matrix']}. Top features: {sorted(m['feature_importances'].items(), key=lambda x: x[1], reverse=True)[:3]}.", styles["Normal"]), Spacer(1, 6),
             Paragraph(f"Backtest {b['event']}: predicted {b['predicted_cells']} vs actual {b['actual_cells']}, IoU {b['iou']}, acc {b['accuracy']} (simulated held-out).", styles["Normal"]), Spacer(1, 6)]
    for z in pz["zones"][:5]:
        story += [Paragraph(f"{z['zone_name']}: {z['probability']*100:.0f}% ({z['risk_level']}, conf {z['confidence']}) — {z['reason']}", styles["Normal"])]
    story += [Spacer(1, 6), Paragraph("Limitations: simulated history/terrain; 28x32 grid; first call slow then cached.", styles["Normal"])]
    doc.build(story)
    return Response(content=buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="resqmap-risk-briefing.pdf"'})


@router.get("/routes")
async def export_routes(
    max_zones: int = Query(default=5, ge=1, le=20),
) -> Response:
    """S2-6: GeoJSON export of drone routes (LineStrings + stops)."""
    from app.services.routing_service import plan_search
    search = plan_search(num_drones=3, max_distance_km=200.0, max_zones=max_zones)
    feats = []
    for dr in search["drones"]:
        pts = []
        for s in dr["stops"]:
            from app.services.data_store import get_store as _gs
            z = _gs().get_zone(s["zone_id"])
            if z:
                pts.append([z.longitude, z.latitude])
        if len(pts) >= 2:
            feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": pts}, "properties": {"drone_id": dr["drone_id"], "distance_km": dr["distance_km"]}})
        for s in dr["stops"]:
            from app.services.data_store import get_store as _gs2
            z = _gs2().get_zone(s["zone_id"])
            if z:
                feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [z.longitude, z.latitude]}, "properties": {"drone_id": dr["drone_id"], **s}})
    import json as _json
    return Response(content=_json.dumps({"type": "FeatureCollection", "features": feats}).encode(), media_type="application/geo+json", headers={"Content-Disposition": 'attachment; filename="resqmap-routes.geojson"'})


@router.get("/geojson")
async def export_geojson(
    include_gis: bool = Query(False, description="Include GIS layers in the GeoJSON"),
) -> Response:
    """Export priority zones as GeoJSON (GET endpoint for easy linking)."""
    zones = _build_priority_zones()
    geojson = _zones_to_geojson(zones, include_gis_layers=include_gis)
    json_bytes = json.dumps(geojson, indent=2).encode("utf-8")
    return Response(
        content=json_bytes,
        media_type="application/geo+json",
        headers={"Content-Disposition": 'attachment; filename="resqmap-zones.geojson"'},
    )


def _generate_pdf_report(zones: list[dict[str, Any]]) -> bytes:
    """Generate a PDF report with priority zones table and summary."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate,
        Table,
        TableStyle,
        Paragraph,
        Spacer,
        PageBreak,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=18,
        spaceAfter=6,
        textColor=colors.HexColor("#070b13"),
    )
    subtitle_style = ParagraphStyle(
        "CustomSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#6d7f99"),
        spaceAfter=12,
    )
    header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontSize=8,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )
    cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontSize=7,
        leading=9,
    )

    elements = []

    elements.append(Paragraph("ResQMap AI — Flood Response Priority Zones Report", title_style))
    elements.append(Paragraph(
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | "
        f"Total Zones: {len(zones)} | "
        f"Critical: {sum(1 for z in zones if z['severity'] == 'Critical')} | "
        f"High: {sum(1 for z in zones if z['severity'] == 'High')}",
        subtitle_style,
    ))
    elements.append(Paragraph(
        "Simulated demonstration data. Not for life-critical decisions.",
        subtitle_style,
    ))
    elements.append(Spacer(1, 6))

    severity_colors = {
        "Critical": colors.HexColor("#ff3b5c"),
        "High": colors.HexColor("#ffd23f"),
        "Medium": colors.HexColor("#4aa8ff"),
        "Low": colors.HexColor("#39d98a"),
    }

    headers = ["#", "Zone", "Severity", "Score", "CV Flood %", "Alerts", "Population", "Area (km²)", "Confidence", "Key Reasons"]
    col_widths = [10 * mm, 30 * mm, 18 * mm, 14 * mm, 18 * mm, 12 * mm, 20 * mm, 18 * mm, 16 * mm, 70 * mm]

    table_data = [[Paragraph(h, header_style) for h in headers]]

    for i, zone in enumerate(zones, 1):
        severity_color = severity_colors.get(zone["severity"], colors.grey)
        reasons_text = "; ".join(zone["reasons"][:2]) + ("…" if len(zone["reasons"]) > 2 else "")
        row = [
            Paragraph(str(i), cell_style),
            Paragraph(zone["name"], cell_style),
            Paragraph(
                f'<font color="{severity_color.hexval()}"><b>{zone["severity"]}</b></font>',
                cell_style,
            ),
            Paragraph(str(zone["score"]), cell_style),
            Paragraph(f'{zone["cv_flood_pct"]:.1f}%', cell_style),
            Paragraph(str(zone["sensor_alerts"]), cell_style),
            Paragraph(f'{zone["population_at_risk"]:,}', cell_style),
            Paragraph(f'{zone["area_km2"]:.2f}', cell_style),
            Paragraph(f'{zone["confidence"]:.0%}', cell_style),
            Paragraph(reasons_text, cell_style),
        ]
        table_data.append(row)

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#070b13")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8fafc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.HexColor("#eef2f7")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("Sources & Methodology", styles["Heading3"]))
    elements.append(Paragraph(
        "• Aerial damage (CV): Flood detection from drone imagery via color segmentation.<br/>"
        "• Sensor alerts: Live water-level, rainfall, and seismic sensors within 4 km radius.<br/>"
        "• GIS proximity: River/drain distance, low elevation, population density layers.<br/>"
        "• Priority score: Weighted fusion of CV damage, sensor risk, and GIS factors (0–100).<br/>"
        "• Severity bands: Critical ≥80, High ≥60, Medium ≥40, Low <40.",
        cell_style,
    ))

    doc.build(elements)
    return buffer.getvalue()


def _generate_png_map(zones: list[dict[str, Any]]) -> bytes:
    """Generate a PNG map snapshot of priority zones."""
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1200, 800
    margin = 50

    img = Image.new("RGB", (width, height), "#070b13")
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 28)
        font_subtitle = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
        font_label = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 11)
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 9)
    except Exception:
        font_title = ImageFont.load_default()
        font_subtitle = ImageFont.load_default()
        font_label = ImageFont.load_default()
        font_small = ImageFont.load_default()

    severity_colors = {
        "Critical": "#ff3b5c",
        "High": "#ffd23f",
        "Medium": "#4aa8ff",
        "Low": "#39d98a",
    }

    lats = [z["latitude"] for z in zones]
    lngs = [z["longitude"] for z in zones]
    min_lat, max_lat = min(lats), max(lats)
    min_lng, max_lng = min(lngs), max(lngs)

    lat_range = max_lat - min_lat or 0.01
    lng_range = max_lng - min_lng or 0.01

    plot_width = width - 2 * margin
    plot_height = height - 2 * margin - 60

    def project(lat: float, lng: float) -> tuple[float, float]:
        x = margin + (lng - min_lng) / lng_range * plot_width
        y = margin + 60 + (1 - (lat - min_lat) / lat_range) * plot_height
        return x, y

    draw.rectangle(
        [margin, margin + 60, width - margin, height - margin],
        outline="#223049",
        width=1,
    )

    for zone in zones:
        x, y = project(zone["latitude"], zone["longitude"])
        color = severity_colors.get(zone["severity"], "#6d7f99")
        radius = 6 + (zone["score"] / 100) * 10
        draw.ellipse(
            [x - radius, y - radius, x + radius, y + radius],
            fill=color,
            outline="#ffffff",
            width=1,
        )

    draw.text((margin, margin + 10), "ResQMap — Priority Zones Map", fill="#e7edf7", font=font_title)
    draw.text(
        (margin, margin + 42),
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · {len(zones)} zones",
        fill="#9fb0c9",
        font=font_subtitle,
    )

    legend_x = width - margin - 180
    legend_y = margin + 60
    draw.rectangle([legend_x - 10, legend_y - 10, width - margin + 10, legend_y + 120], fill="#0b1220", outline="#223049")
    draw.text((legend_x, legend_y), "Severity", fill="#e7edf7", font=font_label)
    for i, (sev, color) in enumerate(severity_colors.items()):
        y = legend_y + 24 + i * 20
        draw.ellipse([legend_x, y, legend_x + 14, y + 14], fill=color)
        draw.text((legend_x + 20, y - 2), sev, fill="#e7edf7", font=font_small)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()