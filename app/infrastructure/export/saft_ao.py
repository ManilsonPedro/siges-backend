"""Exportador SAF-T-AO (Standard Audit File for Tax — Angola), best-effort.

⚠️ AVISO IMPORTANTE — NÃO É UM GERADOR CERTIFICADO FISCALMENTE.

A estrutura XML aqui implementada (Header / MasterFiles / GeneralLedgerEntries
/ SourceDocuments, namespace `urn:OECD:StandardAuditFile-Tax:AO_1.01_01`) foi
construída a partir da documentação pública do repositório oficial
(github.com/assoft-portugal/SAF-T-AO), que descreve o modelo em texto —
**não foi validada contra o ficheiro XSD oficial**, que não estava acessível
no momento da implementação. O SAF-T-AO deriva do modelo SAF-T OCDE/Portugal,
mas pode ter diferenças de nomenclatura de campos não confirmadas aqui.

Antes de submeter este ficheiro à AGT (Administração Geral Tributária):
1. Validar contra o XSD oficial `SAF-T-AO1.01_01.xsd` (Decreto Presidencial
   nº 312/18) assim que disponível.
2. Rever com um contabilista/fiscalista certificado em Angola.
3. Confirmar se a obrigatoriedade de facturação electrónica já se aplica à
   empresa (limiar legal: facturação ≥ 25M AOA / ~USD 250.000; obrigatório a
   partir de 2026 para grandes contribuintes, 2027 para os restantes).

O SIGES já regista explicitamente noutro lugar (contabilidade.py) que a
"fatura legal" pode residir num ERP fiscal externo certificado — este
exportador serve como ponto de partida/apoio, não substitui certificação.

Fonte de dados: `VendaModel`/`VendaLinhaModel` (facturação própria da
aplicação), `ClienteModel`, `FornecedorModel`, `ProdutoModel`,
`PlanoContasModel`, `CompanySettingsModel`.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID
from xml.etree import ElementTree as ET
from xml.dom import minidom

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    ClienteModel,
    CompanySettingsModel,
    FornecedorModel,
    PlanoContasModel,
    ProdutoModel,
    VendaLinhaModel,
    VendaModel,
)

SAFT_AO_NAMESPACE = "urn:OECD:StandardAuditFile-Tax:AO_1.01_01"
SAFT_AO_VERSION = "1.01_01"


def _fmt_data(dt: Optional[datetime]) -> str:
    return (dt or datetime.utcnow()).strftime("%Y-%m-%d")


def _fmt_valor(v) -> str:
    return f"{Decimal(v or 0):.2f}"


def _el(parent: ET.Element, tag: str, text: Optional[str] = None) -> ET.Element:
    e = ET.SubElement(parent, tag)
    if text is not None:
        e.text = text
    return e


async def gerar_saft_ao(
    db: AsyncSession, *, company_id: UUID, data_inicio: datetime, data_fim: datetime,
) -> bytes:
    """Gera o XML SAF-T-AO (best-effort) para o período [data_inicio, data_fim].

    Cobre: Header, MasterFiles (GeneralLedgerAccounts, Customer, Supplier,
    Product), SourceDocuments.SalesInvoices (a partir de VendaModel/estado
    concluida). GeneralLedgerEntries não é gerado — o SIGES não tem lançamento
    contabilístico de dupla entrada próprio (ver contabilidade.py), apenas
    agregação sobre MovimentoFinanceiroModel; incluir isso aqui seria inventar
    uma partida dobrada que não existe no sistema.
    """
    root = ET.Element("AuditFile", {"xmlns": SAFT_AO_NAMESPACE})

    # ── Header ──
    header = ET.SubElement(root, "Header")
    _el(header, "AuditFileVersion", SAFT_AO_VERSION)

    cr = await db.execute(select(CompanySettingsModel).where(CompanySettingsModel.company_id == company_id))
    empresa = cr.scalar_one_or_none()
    _el(header, "CompanyID", empresa.nif if empresa and empresa.nif else "")
    _el(header, "TaxRegistrationNumber", empresa.nif if empresa and empresa.nif else "")
    _el(header, "CompanyName", empresa.nome if empresa and empresa.nome else "")
    _el(header, "CompanyAddress", empresa.morada if empresa and empresa.morada else "")
    _el(header, "FiscalYear", str(data_inicio.year))
    _el(header, "StartDate", _fmt_data(data_inicio))
    _el(header, "EndDate", _fmt_data(data_fim))
    _el(header, "CurrencyCode", "AOA")
    _el(header, "DateCreated", _fmt_data(datetime.utcnow()))
    _el(header, "TaxEntity", "Global")
    _el(header, "ProductCompanyTaxID", empresa.nif if empresa and empresa.nif else "")
    _el(header, "ProductID", "SIGES/BI-JENNOS")
    _el(header, "ProductVersion", "1.0.0")

    # ── MasterFiles ──
    master_files = ET.SubElement(root, "MasterFiles")

    # GeneralLedgerAccounts (Plano de Contas)
    contas_r = await db.execute(
        select(PlanoContasModel)
        .where(PlanoContasModel.company_id == company_id)
        .where(PlanoContasModel.deleted_at.is_(None))
        .order_by(PlanoContasModel.codigo)
    )
    for conta in contas_r.scalars().all():
        ga = ET.SubElement(master_files, "GeneralLedgerAccounts")
        _el(ga, "AccountID", conta.codigo)
        _el(ga, "AccountDescription", conta.nome)
        _el(ga, "GroupingCategory", "GR" if conta.tipo == "sintetica" else "GM")

    # Customer
    clientes_r = await db.execute(
        select(ClienteModel)
        .where(ClienteModel.company_id == company_id)
        .where(ClienteModel.deleted_at.is_(None))
    )
    for cli in clientes_r.scalars().all():
        c = ET.SubElement(master_files, "Customer")
        _el(c, "CustomerID", str(cli.id))
        _el(c, "CustomerTaxID", cli.nif or "")
        _el(c, "CompanyName", cli.nome)
        addr = ET.SubElement(c, "BillingAddress")
        _el(addr, "AddressDetail", cli.endereco or "Desconhecido")
        _el(addr, "Country", "AO")
        _el(c, "Telephone", cli.telefone or "")
        _el(c, "Email", cli.email or "")
        _el(c, "SelfBillingIndicator", "0")

    # Supplier
    fornecedores_r = await db.execute(
        select(FornecedorModel)
        .where(FornecedorModel.company_id == company_id)
        .where(FornecedorModel.deleted_at.is_(None))
    )
    for forn in fornecedores_r.scalars().all():
        s = ET.SubElement(master_files, "Supplier")
        _el(s, "SupplierID", str(forn.id))
        _el(s, "SupplierTaxID", forn.nif or "")
        _el(s, "CompanyName", forn.nome)
        addr = ET.SubElement(s, "BillingAddress")
        _el(addr, "AddressDetail", forn.endereco or "Desconhecido")
        _el(addr, "Country", "AO")
        _el(s, "Telephone", forn.telefone or "")
        _el(s, "Email", forn.email or "")

    # Product
    produtos_r = await db.execute(
        select(ProdutoModel)
        .where(ProdutoModel.company_id == company_id)
        .where(ProdutoModel.activo.is_(True))
    )
    for prod in produtos_r.scalars().all():
        p = ET.SubElement(master_files, "Product")
        _el(p, "ProductType", "P")
        _el(p, "ProductCode", prod.sku)
        _el(p, "ProductDescription", prod.nome)
        _el(p, "ProductNumberCode", prod.sku)

    # ── SourceDocuments / SalesInvoices ──
    source_docs = ET.SubElement(root, "SourceDocuments")
    sales_invoices = ET.SubElement(source_docs, "SalesInvoices")

    vendas_r = await db.execute(
        select(VendaModel)
        .where(VendaModel.company_id == company_id)
        .where(VendaModel.estado == "concluida")
        .where(VendaModel.data >= data_inicio)
        .where(VendaModel.data <= data_fim)
        .order_by(VendaModel.data)
    )
    vendas = list(vendas_r.scalars().all())
    _el(sales_invoices, "NumberOfEntries", str(len(vendas)))
    total_debito = sum((Decimal(v.total_liquido) for v in vendas), Decimal("0"))
    _el(sales_invoices, "TotalDebit", _fmt_valor(total_debito))
    _el(sales_invoices, "TotalCredit", "0.00")

    for venda in vendas:
        linhas_r = await db.execute(select(VendaLinhaModel).where(VendaLinhaModel.venda_id == venda.id))
        linhas = list(linhas_r.scalars().all())

        inv = ET.SubElement(sales_invoices, "Invoice")
        _el(inv, "InvoiceNo", venda.numero_fatura_interna or venda.numero_proforma or str(venda.id))
        _el(inv, "InvoiceStatus", "N")  # Normal — best-effort, sem workflow de anulação/rectificação mapeado
        _el(inv, "InvoiceDate", _fmt_data(venda.data))
        _el(inv, "InvoiceType", "FT" if venda.numero_fatura_interna else "PF")  # Fatura vs. Proforma
        _el(inv, "CustomerID", str(venda.cliente_id) if venda.cliente_id else "CONSUMIDOR_FINAL")

        for linha in linhas:
            line = ET.SubElement(inv, "Line")
            _el(line, "ProductCode", linha.sku_snapshot)
            _el(line, "ProductDescription", linha.nome_snapshot)
            _el(line, "Quantity", str(linha.quantidade))
            _el(line, "UnitPrice", _fmt_valor(linha.preco_unitario))
            _el(line, "TaxPercentage", _fmt_valor(linha.iva_pct))
            _el(line, "CreditAmount", _fmt_valor(linha.subtotal))

        totais = ET.SubElement(inv, "DocumentTotals")
        _el(totais, "TaxPayable", _fmt_valor(venda.total_iva))
        _el(totais, "NetTotal", _fmt_valor(venda.total_bruto - venda.total_desconto))
        _el(totais, "GrossTotal", _fmt_valor(venda.total_liquido))

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=False)
    pretty = minidom.parseString(xml_bytes).toprettyxml(indent="  ", encoding="utf-8")
    return pretty


__all__ = ["gerar_saft_ao", "SAFT_AO_VERSION"]
