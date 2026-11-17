# Relevo (TOPODATA / INPE) — fora do pacote

Como os dados são muito pesados para upload, baixe os quatro arquivos pelos links abaixo e coloque-os nesta pasta:

- Altitude, lado oeste: https://data.inpe.br/bdc/data/topodata/v001/23S/48_/23S48_ZN.tif
- Declividade, lado oeste: https://data.inpe.br/bdc/data/topodata/v001/23S/48_/23S48_SN.tif
- Altitude, lado leste: https://data.inpe.br/bdc/data/topodata/v001/23S/465/23S465ZN.tif
- Declividade, lado leste: https://data.inpe.br/bdc/data/topodata/v001/23S/465/23S465SN.tif

Fonte: TOPODATA / INPE (Brazil Data Cube), resolução de 30 m, licença CC-BY-4.0.

Só a etapa 05 (`scripts/05_indice_propensao.py`) usa esses arquivos. O resultado dela já está no pacote,
em `data/modelo/dim_distrito.csv` e `data/staging/relevo_distritos.csv`, então as etapas 06 e 07 e o painel
rodam sem eles. Refazer a etapa 04 regrava `dim_distrito.csv` sem o relevo; nesse caso, rode a 05 de novo.
