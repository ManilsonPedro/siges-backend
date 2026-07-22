"""Geração de PDF via xhtml2pdf com watermark do logo."""
from pathlib import Path
from typing import Optional
from io import BytesIO
import base64
from xhtml2pdf import pisa

from app.config import settings


def _load_logo_base64(logo_path: Optional[str]) -> Optional[str]:
    """Lê o logo do storage e devolve data URI base64 (PNG/JPG only)."""
    if not logo_path:
        return None
    full = Path(settings.storage_path) / logo_path
    if not full.exists():
        return None
    ext = full.suffix.lower().lstrip(".")
    if ext not in {"png", "jpg", "jpeg"}:
        return None
    mime = f"image/{'jpeg' if ext == 'jpg' else ext}"
    data = full.read_bytes()
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _load_logo_watermark_base64(logo_path: Optional[str], opacity: float = 0.07) -> Optional[str]:
    """Versão esbatida do logo (misturada com branco) para servir de watermark.

    Faz alpha blending com fundo branco: output = logo*opacity + white*(1-opacity)
    Devolve data URI PNG.
    """
    if not logo_path:
        return None
    full = Path(settings.storage_path) / logo_path
    if not full.exists():
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(full).convert("RGBA")
        # Achatar transparência sobre fundo branco primeiro
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        flat = bg.convert("RGB")
        # Blend com branco para esbater
        white = Image.new("RGB", flat.size, (255, 255, 255))
        faded = Image.blend(white, flat, max(0.02, min(0.5, opacity)))
        out = BytesIO()
        faded.save(out, format="PNG", optimize=True)
        return f"data:image/png;base64,{base64.b64encode(out.getvalue()).decode('ascii')}"
    except Exception:
        return None


def render_extrato_pdf(
    *,
    titulo: str,
    subtitulo: Optional[str],
    empresa: dict,           # {nome, nif, morada, telefone, email, logo_path}
    entidade: Optional[dict],  # {nome, ...detalhes} OR None se "todos"
    tipo_coluna_aux: str,    # "Conceito" ou "Fornecedor"
    grupos: list[dict],      # [{label, movimentos, totais}, ...] — 1 grupo se singular
    totais_gerais: dict,
    data_emissao: str,
    mostrar_entradas: bool = True,
    mostrar_saidas: bool = True,
) -> bytes:
    """Gera PDF do extrato. Devolve bytes.

    Args:
        mostrar_entradas: se False, esconde 'Total Entradas' (útil quando filtro=saida)
        mostrar_saidas:   se False, esconde 'Total Saídas' (útil quando filtro=entrada)
        Se um dos dois for False, esconde também o SALDO (não faz sentido sem ambos).
    """
    logo_uri = _load_logo_base64(empresa.get("logo_path"))
    watermark_uri = _load_logo_watermark_base64(empresa.get("logo_path"), opacity=0.07)

    # CSS — paleta corporativa, watermark via background
    css = """
    @page {
      size: A4;
      margin: 16mm 14mm;
      @frame watermark_frame {
        -pdf-frame-content: watermark;
        left: 30mm; top: 70mm; width: 150mm; height: 150mm;
      }
    }
    body { font-family: Helvetica, Arial, sans-serif; font-size: 9pt; color: #1a2332; }
    h1 { color: #0b3b6f; font-size: 16pt; margin: 0 0 4px; }
    h2 { color: #1e5a9c; font-size: 11pt; margin: 12px 0 6px; }
    .header { border-bottom: 2px solid #0b3b6f; padding-bottom: 8px; margin-bottom: 10px; }
    .company-name { font-size: 14pt; font-weight: bold; color: #0b3b6f; }
    .company-info { font-size: 8pt; color: #4a5568; }
    .entity-box { background-color: #f4f7fb; border: 1px solid #d8e1eb; padding: 8px 10px; margin: 8px 0; }
    .entity-label { font-size: 8pt; color: #6b7280; font-weight: bold; text-transform: uppercase; }
    .entity-value { font-size: 10pt; color: #1a2332; margin-bottom: 2px; }
    table.movimentos { width: 100%; border-collapse: collapse; margin-top: 6px; }
    table.movimentos th { background-color: #0b3b6f; color: white; padding: 5px; font-size: 8pt; font-weight: bold; text-align: left; }
    table.movimentos td { border: 0.5px solid #d8e1eb; padding: 4px 5px; font-size: 8pt; }
    table.movimentos tr.tipo-entrada td.tipo { color: #166534; font-weight: bold; }
    table.movimentos tr.tipo-saida td.tipo { color: #991B1B; font-weight: bold; }
    .right { text-align: right; }
    .center { text-align: center; }
    .grupo-titulo { background-color: #eaf1f9; padding: 5px 8px; margin-top: 10px; font-weight: bold; color: #0b3b6f; font-size: 10pt; }
    .subtotal { background-color: #f9fafb; font-weight: bold; }
    .total-geral { background-color: #0b3b6f; color: white; padding: 8px 10px; font-size: 11pt; font-weight: bold; margin-top: 12px; }
    .periodo { font-size: 8pt; color: #6b7280; margin-top: 4px; }
    .watermark img { width: 150mm; height: auto; }
    """

    # Header HTML
    header_html = f"""
    <table style="width:100%; border-bottom: 2px solid #0b3b6f; padding-bottom: 8px;">
      <tr>
        <td style="width: 60mm; vertical-align: top;">
          {f'<img src="{logo_uri}" style="max-width: 50mm; max-height: 25mm;" />' if logo_uri else ''}
        </td>
        <td style="vertical-align: top;">
          <div class="company-name">{empresa.get('nome') or 'Financ-BI Jennos'}</div>
          <div class="company-info">
            {('NIF: ' + empresa['nif']) if empresa.get('nif') else ''}
            {(' · ' + empresa['morada']) if empresa.get('morada') else ''}<br/>
            {('Tel: ' + empresa['telefone']) if empresa.get('telefone') else ''}
            {(' · ' + empresa['email']) if empresa.get('email') else ''}
          </div>
        </td>
        <td style="text-align: right; vertical-align: top; width: 40mm; font-size: 8pt; color: #6b7280;">
          Emissão:<br/><strong>{data_emissao}</strong>
        </td>
      </tr>
    </table>
    """

    # Título + subtítulo
    titulo_html = f"""
    <h1>{titulo}</h1>
    {f'<div class="periodo">{subtitulo}</div>' if subtitulo else ''}
    """

    # Bloco da entidade (apenas se for um único)
    entidade_html = ""
    if entidade:
        rows = []
        for k, v in entidade.items():
            if not v: continue
            rows.append(f'<tr><td class="entity-label" style="width: 30%;">{k}</td><td class="entity-value">{v}</td></tr>')
        entidade_html = f'<div class="entity-box"><table>{"".join(rows)}</table></div>'

    # Grupos de movimentos
    grupos_html = ""
    for g in grupos:
        if len(grupos) > 1:
            grupos_html += f'<div class="grupo-titulo">{g["label"]} · {g["totais"]["count"]} mov.</div>'
        grupos_html += '<table class="movimentos"><thead><tr>'
        grupos_html += '<th style="width: 4%">#</th>'
        grupos_html += '<th style="width: 12%">Código</th>'
        grupos_html += '<th style="width: 10%">Data</th>'
        grupos_html += f'<th>{tipo_coluna_aux}</th>'
        grupos_html += '<th style="width: 9%">Tipo</th>'
        grupos_html += '<th style="width: 7%" class="center">Fundo</th>'
        grupos_html += '<th style="width: 16%" class="right">Valor (AOA)</th>'
        grupos_html += '</tr></thead><tbody>'
        for i, m in enumerate(g["movimentos"], 1):
            tipo_class = "tipo-entrada" if m["tipo_movimento"] == "entrada" else "tipo-saida"
            tipo_label = "Entrada" if m["tipo_movimento"] == "entrada" else "Saída"
            grupos_html += f'<tr class="{tipo_class}">'
            grupos_html += f'<td>{i}</td>'
            grupos_html += f'<td>{m.get("codigo") or "—"}</td>'
            grupos_html += f'<td>{(m.get("data") or "")[:10]}</td>'
            grupos_html += f'<td>{m.get("aux_nome") or "—"}</td>'
            grupos_html += f'<td class="tipo">{tipo_label}</td>'
            grupos_html += f'<td class="center">{m.get("fundo_tipo") or "BCS"}</td>'
            grupos_html += f'<td class="right">{m["valor"]:,.2f}</td>'
            grupos_html += '</tr>'
        # Subtotal do grupo
        if len(grupos) > 1:
            t = g["totais"]
            grupos_html += '<tr class="subtotal">'
            grupos_html += f'<td colspan="6" class="right">Subtotal {g["label"]}:</td>'
            grupos_html += f'<td class="right">{t["saldo"]:,.2f}</td>'
            grupos_html += '</tr>'
        grupos_html += '</tbody></table>'

    # Total geral — esconde Entradas/Saídas/Saldo consoante filtro
    partes = []
    if mostrar_entradas:
        partes.append(f"Total Entradas: {totais_gerais['entradas']:,.2f} AOA")
    if mostrar_saidas:
        partes.append(f"Total Saídas: {totais_gerais['saidas']:,.2f} AOA")
    if mostrar_entradas and mostrar_saidas:
        partes.append(f"SALDO: {totais_gerais['saldo']:,.2f} AOA")
    partes.append(f"{totais_gerais['count']} movimento(s)")
    sep = "&nbsp;&nbsp;|&nbsp;&nbsp;"
    total_html = f'<div class="total-geral">{sep.join(partes)}</div>'

    # Watermark — imagem PRÉ-ESBATIDA (já com fundo branco), sem precisar de opacity CSS
    watermark_html = ""
    if watermark_uri:
        watermark_html = f'<div id="watermark" class="watermark"><img src="{watermark_uri}" /></div>'

    # HTML completo
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>{css}</style>
</head>
<body>
{watermark_html}
{header_html}
{titulo_html}
{entidade_html}
<h2>Movimentos</h2>
{grupos_html}
{total_html}
</body>
</html>"""

    # Render
    out = BytesIO()
    result = pisa.CreatePDF(html, dest=out, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"Erro ao gerar PDF: {result.err}")
    return out.getvalue()
