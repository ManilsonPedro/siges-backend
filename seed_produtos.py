"""Seed histórico dos produtos KITOKA da Aquasan Angola — DESATIVADO.

O SIGES deixou de ser centrado no negócio Aquasan/KITOKA (ver
PROMPT_SISTEMA_SIGES_SPRINTS.md, Sprint 0 e
SIGES_BI_JENNOS_Documento_Visao_Arquitetural.md Secção 2.4). Este script
já não semeia nenhum produto — mantido apenas para não quebrar o import
em `app/main.py` (que o chama no arranque). `run()` é um no-op.
"""


def run():
    print("[skip] seed_produtos: desativado — SIGES já não semeia produtos KITOKA/Aquasan.")


if __name__ == "__main__":
    run()
