"""Geração de PDF de documentos de abastecimento de água
(proforma/fatura/fatura-recibo/recibo/ordem de receção).

Estilo visual espelha `proforma_pdf.py` (venda) para consistência do SIGES,
mas o abastecimento não tem linhas de artigo/pagamentos como uma venda —
é um documento de fornecedor, não um documento fiscal, por isso não reutiliza
diretamente `render_proforma_html`.

Ver PROMPT_GESTAO_AGUA_SPRINTS.md, Fase 5.
"""
from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from typing import Optional

from xhtml2pdf import pisa

from app.infrastructure.database.models import AbastecimentoAguaModel


def _fmt(v) -> str:
    try:
        return f"{Decimal(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", " ")
    except Exception:
        return str(v)


_TIPO_TITULO = {
    "proforma": "PROFORMA",
    "fatura": "FATURA",
    "fatura_recibo": "FATURA-RECIBO",
    "recibo": "RECIBO",
    "ordem_recepcao": "ORDEM DE RECEÇÃO",
}

_ESTADO_LABEL = {
    "registado": "Registado", "aprovado": "Aprovado", "documentado": "Documentado",
    "pago": "Pago", "concluido": "Concluído",
}


def render_abastecimento_html(
    abastecimento: AbastecimentoAguaModel, tipo_documento: str, *,
    empresa_nome: str = "", fornecedor_nome: str = "", fornecedor_nif: str = "",
    tanque_nome: str = "", filial_nome: Optional[str] = None,
) -> str:
    titulo = _TIPO_TITULO.get(tipo_documento, tipo_documento.upper())
    estado_label = _ESTADO_LABEL.get(abastecimento.estado, abastecimento.estado.capitalize())
    data_str = abastecimento.data.strftime("%d/%m/%Y %H:%M") if abastecimento.data else "-"

    return f"""<html>
<head>
<meta charset="utf-8"/>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: Helvetica, Arial, sans-serif; font-size: 9.5pt; color: #1a1a2e; }}
  .page {{ padding: 28pt 32pt 24pt 32pt; }}
  .header-wrap {{ width: 100%; border-bottom: 3pt solid #0a5fa8; padding-bottom: 14pt; margin-bottom: 20pt; }}
  .header-left {{ display: inline-block; width: 58%; vertical-align: top; }}
  .header-right {{ display: inline-block; width: 40%; vertical-align: top; text-align: right; }}
  .empresa-nome {{ font-size: 16pt; font-weight: bold; color: #0a5fa8; }}
  .empresa-sub {{ font-size: 8pt; color: #6b7a8d; margin-top: 2pt; }}
  .doc-titulo {{ font-size: 20pt; font-weight: bold; color: #0a5fa8; }}
  .doc-numero {{ font-size: 11pt; color: #444; margin-top: 2pt; }}
  .badge {{ display: inline-block; padding: 2pt 8pt; border-radius: 4pt; font-size: 8pt; font-weight: bold; color: #fff; background: #0a5fa8; margin-top: 4pt; }}
  .info-row {{ width: 100%; margin-bottom: 18pt; }}
  .info-card {{ display: inline-block; width: 31%; vertical-align: top; background: #f4f7fb; border-left: 3pt solid #0a5fa8; border-radius: 0 4pt 4pt 0; padding: 8pt 10pt; margin-right: 2%; }}
  .info-card:last-child {{ margin-right: 0; }}
  .info-label {{ font-size: 7.5pt; color: #7a8899; text-transform: uppercase; margin-bottom: 2pt; }}
  .info-value {{ font-size: 9.5pt; font-weight: bold; color: #1a1a2e; }}
  .section-title {{ font-size: 9pt; font-weight: bold; color: #0a5fa8; text-transform: uppercase; border-bottom: 1pt solid #d0dcea; padding-bottom: 3pt; margin-bottom: 6pt; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 14pt; }}
  thead tr {{ background: #0a5fa8; color: #fff; }}
  thead th {{ padding: 5pt 7pt; font-size: 8pt; font-weight: bold; text-align: left; }}
  tbody td {{ padding: 5pt 7pt; font-size: 9pt; border-bottom: 1pt solid #e8edf3; }}
  .r {{ text-align: right; }}
  .bold {{ font-weight: bold; }}
  .total-final {{ background: #0a5fa8; color: #fff !important; font-size: 10.5pt; font-weight: bold; }}
  .total-final td {{ color: #fff !important; border-bottom: none !important; }}
  .footer {{ margin-top: 28pt; border-top: 1pt solid #d0dcea; padding-top: 8pt; font-size: 7.5pt; color: #9aabb8; text-align: center; }}
</style>
</head>
<body>
<div class="page">
  <div class="header-wrap">
    <div class="header-left">
      <div class="empresa-nome">{empresa_nome}</div>
      <div class="empresa-sub">Gestão de Recursos Hídricos</div>
    </div>
    <div class="header-right">
      <div class="doc-titulo">{titulo}</div>
      <div class="doc-numero">{abastecimento.numero or "(sem número)"}</div>
      <div class="badge">{estado_label}</div>
    </div>
  </div>

  <div class="info-row">
    <div class="info-card">
      <div class="info-label">Fornecedor</div>
      <div class="info-value">{fornecedor_nome or "—"}</div>
      <div class="info-label" style="margin-top:4pt">NIF: {fornecedor_nif or "—"}</div>
    </div>
    <div class="info-card">
      <div class="info-label">Tanque</div>
      <div class="info-value">{tanque_nome or "—"}</div>
    </div>
    <div class="info-card">
      <div class="info-label">Data</div>
      <div class="info-value">{data_str}</div>
      {f'<div class="info-label" style="margin-top:4pt">Filial: {filial_nome}</div>' if filial_nome else ''}
    </div>
  </div>

  <div class="section-title">Detalhe do Abastecimento</div>
  <table>
    <thead>
      <tr>
        <th>Quantidade (L)</th>
        <th class="r">Valor por Litro</th>
        <th class="r">Custo Total</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>{_fmt(abastecimento.quantidade_litros)}</td>
        <td class="r">{_fmt(abastecimento.valor_por_litro)} AOA</td>
        <td class="r bold">{_fmt(abastecimento.custo_total)} AOA</td>
      </tr>
      <tr class="total-final">
        <td colspan="2" class="bold">TOTAL</td>
        <td class="r bold">{_fmt(abastecimento.custo_total)} AOA</td>
      </tr>
    </tbody>
  </table>

  {f'<div class="section-title">Observações</div><p style="font-size:9pt;color:#3a4a5a">{abastecimento.observacoes}</p>' if abastecimento.observacoes else ''}

  <div class="footer">
    {empresa_nome} &nbsp;·&nbsp; Documento gerado automaticamente &nbsp;·&nbsp; {data_str}
  </div>
</div>
</body>
</html>"""


def gerar_abastecimento_pdf(abastecimento: AbastecimentoAguaModel, tipo_documento: str, **ctx) -> bytes:
    html = render_abastecimento_html(abastecimento, tipo_documento, **ctx)
    out = BytesIO()
    pisa.CreatePDF(src=html, dest=out, encoding="utf-8")
    return out.getvalue()


__all__ = ["gerar_abastecimento_pdf", "render_abastecimento_html"]
