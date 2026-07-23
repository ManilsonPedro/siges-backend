"""Geração de PDF de proforma de venda.

NOTA: Proforma é documento **interno** — não substitui factura fiscal.
Quando a fatura correspondente é emitida, o nº é registado manualmente
em ``VendaModel.numero_fatura_interna``.
"""
from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from typing import Optional

from xhtml2pdf import pisa

from app.infrastructure.database.models import VendaModel


def _fmt(v) -> str:
    try:
        return f"{Decimal(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", " ")
    except Exception:
        return str(v)


_ESTADO_LABEL = {
    "aberta": "Em aberto",
    "concluida": "Concluída",
    "cancelada": "Cancelada",
    "pendente": "Pendente",
}

_ESTADO_COLOR = {
    "aberta": "#1d6fcf",
    "concluida": "#1a7a4a",
    "cancelada": "#c0392b",
    "pendente": "#d68910",
}

_FORMA_LABEL = {
    "tpa": "TPA / Cartão",
    "numerario": "Numerário",
    "transferencia": "Transferência",
    "cheque": "Cheque",
    "credito": "Crédito",
}


def render_proforma_html(venda: VendaModel, *, empresa_nome: str = "",
                         cliente_nome: Optional[str] = None,
                         armazem_nome: Optional[str] = None) -> str:

    estado_raw = str(venda.estado).lower()
    estado_label = _ESTADO_LABEL.get(estado_raw, venda.estado.capitalize())
    estado_color = _ESTADO_COLOR.get(estado_raw, "#555")

    data_str = venda.data.strftime("%d/%m/%Y %H:%M") if venda.data else "-"

    linhas_html = []
    for i, ln in enumerate(venda.linhas):
        row_bg = "#f9fafb" if i % 2 == 0 else "#ffffff"
        linhas_html.append(
            f'<tr style="background:{row_bg}">'
            f'<td class="mono">{ln.sku_snapshot}</td>'
            f'<td>{ln.nome_snapshot}</td>'
            f'<td class="r">{_fmt(ln.quantidade)}</td>'
            f'<td class="r">{_fmt(ln.preco_unitario)}</td>'
            f'<td class="r c-muted">{_fmt(ln.iva_pct)}%</td>'
            f'<td class="r c-muted">{_fmt(ln.desconto_pct)}%</td>'
            f'<td class="r bold">{_fmt(ln.subtotal)} AOA</td>'
            f'</tr>'
        )

    pagamentos_html = []
    for p in venda.pagamentos:
        forma_label = _FORMA_LABEL.get(str(p.forma).lower(), str(p.forma).upper())
        ref = p.ref_externa or "—"
        pagamentos_html.append(
            f'<tr>'
            f'<td>{forma_label}</td>'
            f'<td class="mono c-muted">{ref}</td>'
            f'<td class="r bold">{_fmt(p.valor)} AOA</td>'
            f'</tr>'
        )

    if venda.numero_fatura_interna:
        aviso_bg = "#eaf4ec"
        aviso_border = "#27ae60"
        aviso_icon = "&#10003;"
        aviso_text = f"Documento associado à factura: <b>{venda.numero_fatura_interna}</b>"
    else:
        aviso_bg = "#fff8e1"
        aviso_border = "#f0ad00"
        aviso_icon = "&#9888;"
        aviso_text = "Documento INTERNO. Não substitui factura fiscal."

    return f"""<html>
<head>
<meta charset="utf-8"/>
<style>
  /* ── Reset & base ── */
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: Helvetica, Arial, sans-serif;
    font-size: 9.5pt;
    color: #1a1a2e;
    background: #ffffff;
  }}

  /* ── Page layout ── */
  .page {{
    padding: 28pt 32pt 24pt 32pt;
  }}

  /* ── Header ── */
  .header-wrap {{
    width: 100%;
    border-bottom: 3pt solid #0a5fa8;
    padding-bottom: 14pt;
    margin-bottom: 20pt;
  }}
  .header-left {{
    display: inline-block;
    width: 58%;
    vertical-align: top;
  }}
  .header-right {{
    display: inline-block;
    width: 40%;
    vertical-align: top;
    text-align: right;
  }}
  .empresa-nome {{
    font-size: 16pt;
    font-weight: bold;
    color: #0a5fa8;
    letter-spacing: 0.5pt;
  }}
  .empresa-sub {{
    font-size: 8pt;
    color: #6b7a8d;
    margin-top: 2pt;
  }}
  .doc-titulo {{
    font-size: 20pt;
    font-weight: bold;
    color: #0a5fa8;
    letter-spacing: -0.5pt;
  }}
  .doc-numero {{
    font-size: 11pt;
    color: #444;
    margin-top: 2pt;
  }}
  .badge {{
    display: inline-block;
    padding: 2pt 8pt;
    border-radius: 4pt;
    font-size: 8pt;
    font-weight: bold;
    color: #fff;
    background: {estado_color};
    margin-top: 4pt;
  }}

  /* ── Info cards ── */
  .info-row {{
    width: 100%;
    margin-bottom: 18pt;
  }}
  .info-card {{
    display: inline-block;
    width: 31%;
    vertical-align: top;
    background: #f4f7fb;
    border-left: 3pt solid #0a5fa8;
    border-radius: 0 4pt 4pt 0;
    padding: 8pt 10pt;
    margin-right: 2%;
  }}
  .info-card:last-child {{ margin-right: 0; }}
  .info-label {{
    font-size: 7.5pt;
    color: #7a8899;
    text-transform: uppercase;
    letter-spacing: 0.4pt;
    margin-bottom: 2pt;
  }}
  .info-value {{
    font-size: 9.5pt;
    font-weight: bold;
    color: #1a1a2e;
  }}

  /* ── Section title ── */
  .section-title {{
    font-size: 9pt;
    font-weight: bold;
    color: #0a5fa8;
    text-transform: uppercase;
    letter-spacing: 0.5pt;
    border-bottom: 1pt solid #d0dcea;
    padding-bottom: 3pt;
    margin-bottom: 6pt;
  }}

  /* ── Tabelas ── */
  table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 14pt;
  }}
  thead tr {{
    background: #0a5fa8;
    color: #ffffff;
  }}
  thead th {{
    padding: 5pt 7pt;
    font-size: 8pt;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.3pt;
    text-align: left;
    border: none;
  }}
  tbody td {{
    padding: 5pt 7pt;
    font-size: 9pt;
    border-bottom: 1pt solid #e8edf3;
    vertical-align: middle;
  }}

  /* ── Totais ── */
  .totais-wrap {{
    width: 100%;
    margin-bottom: 18pt;
  }}
  .totais-spacer {{
    display: inline-block;
    width: 54%;
    vertical-align: top;
  }}
  .totais-block {{
    display: inline-block;
    width: 44%;
    vertical-align: top;
  }}
  .totais-block table {{
    margin: 0;
  }}
  .totais-block td {{
    padding: 4pt 8pt;
    border: none;
    font-size: 9pt;
    color: #3a4a5a;
    border-bottom: 1pt solid #e8edf3;
  }}
  .totais-block td.r {{ text-align: right; }}
  .total-final {{
    background: #0a5fa8;
    color: #ffffff !important;
    font-size: 10.5pt;
    font-weight: bold;
  }}
  .total-final td {{ color: #ffffff !important; border-bottom: none !important; }}

  /* ── Utilidades ── */
  .r  {{ text-align: right; }}
  .bold {{ font-weight: bold; }}
  .mono {{ font-family: "Courier New", monospace; font-size: 8.5pt; }}
  .c-muted {{ color: #6b7a8d; }}

  /* ── Aviso ── */
  .aviso {{
    background: {aviso_bg};
    border-left: 4pt solid {aviso_border};
    border-radius: 0 4pt 4pt 0;
    padding: 7pt 10pt;
    font-size: 8.5pt;
    color: #2c3e50;
    margin-top: 4pt;
  }}

  /* ── Rodapé ── */
  .footer {{
    margin-top: 28pt;
    border-top: 1pt solid #d0dcea;
    padding-top: 8pt;
    font-size: 7.5pt;
    color: #9aabb8;
    text-align: center;
  }}
</style>
</head>
<body>
<div class="page">

  <!-- CABEÇALHO -->
  <div class="header-wrap">
    <div class="header-left">
      <div class="empresa-nome">{empresa_nome}</div>
      <div class="empresa-sub">Sistema de Gestão Financeira</div>
    </div>
    <div class="header-right">
      <div class="doc-titulo">PROFORMA</div>
      <div class="doc-numero">{venda.numero_proforma or "(sem número)"}</div>
      <div class="badge">{estado_label}</div>
    </div>
  </div>

  <!-- INFO CARDS -->
  <div class="info-row">
    <div class="info-card">
      <div class="info-label">Cliente</div>
      <div class="info-value">{cliente_nome or "Consumidor Final"}</div>
    </div>
    <div class="info-card">
      <div class="info-label">Armazém</div>
      <div class="info-value">{armazem_nome or "—"}</div>
    </div>
    <div class="info-card">
      <div class="info-label">Data de Emissão</div>
      <div class="info-value">{data_str}</div>
    </div>
  </div>

  <!-- TABELA DE LINHAS -->
  <div class="section-title">Artigos</div>
  <table>
    <thead>
      <tr>
        <th style="width:14%">SKU</th>
        <th style="width:34%">Produto / Serviço</th>
        <th class="r" style="width:8%">Qtd</th>
        <th class="r" style="width:12%">Preço Unit.</th>
        <th class="r" style="width:8%">IVA</th>
        <th class="r" style="width:8%">Desc.</th>
        <th class="r" style="width:16%">Subtotal</th>
      </tr>
    </thead>
    <tbody>
      {''.join(linhas_html) or '<tr><td colspan="7" style="text-align:center;color:#999;padding:12pt">Sem artigos registados</td></tr>'}
    </tbody>
  </table>

  <!-- TOTAIS -->
  <div class="totais-wrap">
    <div class="totais-spacer"></div>
    <div class="totais-block">
      <table>
        <tr>
          <td>Total Bruto</td>
          <td class="r">{_fmt(venda.total_bruto)} AOA</td>
        </tr>
        <tr>
          <td>Desconto</td>
          <td class="r c-muted">- {_fmt(venda.total_desconto)} AOA</td>
        </tr>
        <tr>
          <td>IVA</td>
          <td class="r c-muted">{_fmt(venda.total_iva)} AOA</td>
        </tr>
        <tr class="total-final">
          <td class="bold">TOTAL LÍQUIDO</td>
          <td class="r bold">{_fmt(venda.total_liquido)} AOA</td>
        </tr>
      </table>
    </div>
  </div>

  <!-- PAGAMENTOS -->
  <div class="section-title">Pagamentos Registados</div>
  <table>
    <thead>
      <tr>
        <th style="width:35%">Forma de Pagamento</th>
        <th style="width:45%">Referência</th>
        <th class="r" style="width:20%">Valor</th>
      </tr>
    </thead>
    <tbody>
      {''.join(pagamentos_html) or '<tr><td colspan="3" style="text-align:center;color:#999;padding:10pt">Sem pagamentos registados</td></tr>'}
    </tbody>
  </table>

  <!-- AVISO -->
  <div class="aviso">
    <b>{aviso_icon}</b>&nbsp;{aviso_text}
  </div>

  <!-- RODAPÉ -->
  <div class="footer">
    {empresa_nome} &nbsp;·&nbsp; Documento gerado automaticamente &nbsp;·&nbsp; {data_str}
  </div>

</div>
</body>
</html>"""


def gerar_proforma_pdf(venda: VendaModel, **ctx) -> bytes:
    """Renderiza HTML → PDF bytes."""
    html = render_proforma_html(venda, **ctx)
    out = BytesIO()
    pisa.CreatePDF(src=html, dest=out, encoding="utf-8")
    return out.getvalue()


__all__ = ["gerar_proforma_pdf", "render_proforma_html"]
