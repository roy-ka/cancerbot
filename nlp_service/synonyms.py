# MeSH-based oncology synonym map.
# Keys are canonical terms (lowercase). Values are additional search terms.
# Lookup works both ways: entity matches a key OR a value → all terms returned.

ONCOLOGY_SYNONYMS: dict[str, list[str]] = {
    # --- Cancer types ---
    "breast cancer": ["breast neoplasm", "mammary carcinoma", "breast carcinoma", "carcinoma of breast"],
    "lung cancer": ["lung neoplasm", "pulmonary carcinoma", "bronchogenic carcinoma", "non-small cell lung cancer", "NSCLC", "small cell lung cancer", "SCLC"],
    "colorectal cancer": ["colon cancer", "rectal cancer", "colorectal carcinoma", "colon carcinoma", "colorectal neoplasm"],
    "prostate cancer": ["prostate neoplasm", "prostatic carcinoma", "carcinoma of prostate"],
    "pancreatic cancer": ["pancreatic neoplasm", "pancreatic carcinoma", "carcinoma of pancreas", "pancreatic adenocarcinoma"],
    "ovarian cancer": ["ovarian neoplasm", "ovarian carcinoma", "carcinoma of ovary"],
    "cervical cancer": ["cervical neoplasm", "cervical carcinoma", "carcinoma of cervix"],
    "endometrial cancer": ["uterine cancer", "endometrial carcinoma", "uterine carcinoma", "carcinoma of endometrium"],
    "gastric cancer": ["stomach cancer", "gastric neoplasm", "stomach neoplasm", "gastric carcinoma"],
    "hepatocellular carcinoma": ["liver cancer", "hepatic carcinoma", "HCC", "liver neoplasm"],
    "glioblastoma": ["glioblastoma multiforme", "GBM", "grade IV glioma", "high-grade glioma"],
    "glioma": ["brain tumor", "brain neoplasm", "glial tumor", "astrocytoma"],
    "melanoma": ["malignant melanoma", "skin cancer", "cutaneous melanoma", "skin neoplasm"],
    "leukemia": ["blood cancer", "hematologic malignancy", "leukaemia", "leukemic"],
    "acute myeloid leukemia": ["AML", "acute myelogenous leukemia", "acute myelocytic leukemia"],
    "acute lymphoblastic leukemia": ["ALL", "acute lymphocytic leukemia", "acute lymphoid leukemia"],
    "chronic lymphocytic leukemia": ["CLL", "chronic lymphoid leukemia"],
    "chronic myeloid leukemia": ["CML", "chronic myelogenous leukemia"],
    "lymphoma": ["lymphatic cancer", "lymph node cancer", "lymphoid neoplasm"],
    "hodgkin lymphoma": ["hodgkin disease", "hodgkin's lymphoma", "hodgkins lymphoma"],
    "non-hodgkin lymphoma": ["NHL", "non-hodgkins lymphoma", "diffuse large B-cell lymphoma", "DLBCL"],
    "multiple myeloma": ["plasma cell myeloma", "myeloma", "plasmacytoma"],
    "thyroid cancer": ["thyroid neoplasm", "thyroid carcinoma", "papillary thyroid carcinoma", "follicular thyroid carcinoma"],
    "renal cell carcinoma": ["kidney cancer", "renal cancer", "RCC", "clear cell carcinoma", "renal neoplasm"],
    "bladder cancer": ["bladder neoplasm", "urothelial carcinoma", "transitional cell carcinoma"],
    "sarcoma": ["soft tissue sarcoma", "bone sarcoma", "osteosarcoma", "Ewing sarcoma", "rhabdomyosarcoma"],
    "mesothelioma": ["malignant mesothelioma", "pleural mesothelioma", "peritoneal mesothelioma"],
    "neuroblastoma": ["adrenal neuroblastoma", "peripheral neuroblastic tumor"],
    "retinoblastoma": ["eye cancer", "ocular tumor", "retinal tumor"],

    # --- Molecular targets & biomarkers ---
    "EGFR": ["epidermal growth factor receptor", "ErbB1", "HER1", "EGFR mutation"],
    "HER2": ["ERBB2", "HER2/neu", "human epidermal growth factor receptor 2", "HER2 amplification"],
    "VEGF": ["vascular endothelial growth factor", "VEGFA", "angiogenesis factor"],
    "PD-L1": ["CD274", "B7-H1", "programmed death ligand 1", "PDL1"],
    "PD-1": ["PDCD1", "CD279", "programmed cell death protein 1"],
    "CTLA-4": ["CD152", "cytotoxic T-lymphocyte antigen 4", "ipilimumab target"],
    "BRCA1": ["breast cancer gene 1", "BRCA1 mutation", "BRCA1 deficiency"],
    "BRCA2": ["breast cancer gene 2", "BRCA2 mutation", "BRCA2 deficiency"],
    "TP53": ["p53", "tumor protein p53", "TP53 mutation", "p53 pathway"],
    "KRAS": ["KRAS mutation", "KRAS oncogene", "Kirsten RAS", "RAS mutation"],
    "BRAF": ["BRAF mutation", "BRAF V600E", "B-raf kinase"],
    "ALK": ["anaplastic lymphoma kinase", "ALK rearrangement", "ALK fusion"],
    "ROS1": ["ROS1 rearrangement", "ROS1 fusion", "ROS proto-oncogene"],
    "MET": ["MET amplification", "MET exon 14", "hepatocyte growth factor receptor", "c-MET"],
    "PTEN": ["phosphatase and tensin homolog", "PTEN loss", "PTEN mutation"],
    "CDK4": ["cyclin-dependent kinase 4", "CDK4/6", "cell cycle kinase"],
    "CDK6": ["cyclin-dependent kinase 6", "CDK4/6"],
    "PIK3CA": ["PI3K mutation", "PIK3CA mutation", "PI3K alpha"],
    "mTOR": ["mechanistic target of rapamycin", "mammalian target of rapamycin", "mTORC1", "mTORC2"],
    "RB1": ["retinoblastoma protein", "pRb", "RB1 mutation"],
    "MSI": ["microsatellite instability", "MSI-H", "mismatch repair deficiency", "dMMR"],
    "TMB": ["tumor mutational burden", "tumor mutation burden"],

    # --- Signaling pathways ---
    "PI3K pathway": ["PI3K/AKT", "PI3K/AKT/mTOR", "phosphoinositide 3-kinase", "PI3K signaling"],
    "MAPK pathway": ["RAS/MAPK", "ERK pathway", "MEK/ERK", "mitogen-activated protein kinase"],
    "Wnt pathway": ["Wnt signaling", "beta-catenin pathway", "canonical Wnt"],
    "Notch pathway": ["Notch signaling", "Notch receptor", "Notch1"],
    "Hedgehog pathway": ["Sonic hedgehog", "SHH pathway", "GLI transcription factor"],
    "NF-kB pathway": ["nuclear factor kappa B", "NF-κB signaling", "NF-kB signaling"],
    "JAK-STAT pathway": ["JAK/STAT", "Janus kinase", "STAT3 pathway"],
    "apoptosis": ["programmed cell death", "caspase activation", "cell death pathway"],
    "autophagy": ["autophagic cell death", "mTOR-autophagy", "lysosomal degradation"],
    "angiogenesis": ["tumor vascularization", "blood vessel formation", "neovascularization", "VEGF-driven angiogenesis"],
    "Warburg effect": ["aerobic glycolysis", "tumor glycolysis", "cancer metabolism", "Warburg metabolism"],

    # --- Treatments ---
    "chemotherapy": ["cytotoxic therapy", "antineoplastic therapy", "cancer chemotherapy", "chemo"],
    "immunotherapy": ["cancer immunotherapy", "immune checkpoint therapy", "biological therapy"],
    "targeted therapy": ["molecularly targeted therapy", "tyrosine kinase inhibitor", "TKI"],
    "radiation therapy": ["radiotherapy", "radiation treatment", "external beam radiation", "EBRT"],
    "surgery": ["surgical resection", "tumor resection", "oncologic surgery", "debulking"],
    "CAR-T therapy": ["chimeric antigen receptor T-cell", "CAR T-cell therapy", "adoptive cell therapy"],
    "bone marrow transplant": ["hematopoietic stem cell transplant", "HSCT", "stem cell transplant", "BMT"],
    "hormone therapy": ["endocrine therapy", "anti-hormonal therapy", "androgen deprivation", "ADT"],
    "PARP inhibitor": ["PARPi", "PARP1 inhibitor", "poly ADP-ribose polymerase inhibitor"],

    # --- Specific drugs ---
    "metformin": ["biguanide", "glucophage", "metformin hydrochloride", "AMPK activator"],
    "rapamycin": ["sirolimus", "mTOR inhibitor", "rapamune"],
    "cisplatin": ["cis-platinum", "platinol", "platinum-based chemotherapy"],
    "carboplatin": ["paraplatin", "platinum compound"],
    "doxorubicin": ["adriamycin", "hydroxydaunorubicin", "anthracycline"],
    "paclitaxel": ["taxol", "taxane", "antimicrotubule agent"],
    "docetaxel": ["taxotere", "taxane"],
    "bevacizumab": ["avastin", "anti-VEGF antibody", "VEGF inhibitor"],
    "trastuzumab": ["herceptin", "HER2 antibody", "anti-HER2"],
    "pembrolizumab": ["keytruda", "anti-PD-1", "PD-1 inhibitor"],
    "nivolumab": ["opdivo", "anti-PD-1", "BMS-936558"],
    "ipilimumab": ["yervoy", "anti-CTLA-4", "CTLA-4 inhibitor"],
    "imatinib": ["gleevec", "glivec", "STI571", "BCR-ABL inhibitor"],
    "erlotinib": ["tarceva", "EGFR inhibitor", "OSI-774"],
    "gefitinib": ["iressa", "EGFR inhibitor"],
    "osimertinib": ["tagrisso", "third-generation EGFR inhibitor", "AZD9291"],
    "vemurafenib": ["zelboraf", "BRAF inhibitor", "PLX4032"],
    "sorafenib": ["nexavar", "multikinase inhibitor", "RAF inhibitor"],
    "sunitinib": ["sutent", "multi-target TKI"],
    "tamoxifen": ["nolvadex", "selective estrogen receptor modulator", "SERM"],
    "letrozole": ["femara", "aromatase inhibitor"],
    "palbociclib": ["ibrance", "CDK4/6 inhibitor"],
    "olaparib": ["lynparza", "PARP inhibitor", "PARPi"],

    # --- Metabolism ---
    "glycolysis": ["glucose metabolism", "aerobic glycolysis", "lactate production", "hexokinase"],
    "oxidative phosphorylation": ["OXPHOS", "mitochondrial respiration", "electron transport chain"],
    "glutamine metabolism": ["glutaminolysis", "glutamine addiction", "glutamine uptake"],
    "lipid metabolism": ["fatty acid synthesis", "lipogenesis", "FASN", "lipid biosynthesis"],
    "lactate": ["lactic acid", "lactate dehydrogenase", "LDH", "Warburg effect"],

    # --- General oncology ---
    "metastasis": ["metastatic disease", "distant metastasis", "tumor spread", "cancer spread", "secondary tumor"],
    "tumor microenvironment": ["TME", "cancer stroma", "tumor stroma", "immune microenvironment"],
    "cancer stem cell": ["tumor-initiating cell", "CSC", "cancer stem-like cell"],
    "drug resistance": ["chemoresistance", "treatment resistance", "acquired resistance", "primary resistance"],
    "tumor suppressor": ["tumor suppressor gene", "anti-oncogene", "growth inhibitor"],
    "oncogene": ["proto-oncogene", "cancer gene", "driver mutation"],
    "clinical trial": ["clinical study", "phase I trial", "phase II trial", "phase III trial", "randomized controlled trial"],
    "biomarker": ["predictive biomarker", "prognostic biomarker", "cancer biomarker", "tumor marker"],
    "liquid biopsy": ["circulating tumor DNA", "ctDNA", "cell-free DNA", "cfDNA", "circulating tumor cells"],
    "DNA methylation": ["epigenetic modification", "CpG methylation", "promoter methylation"],
    "histone modification": ["chromatin remodeling", "epigenetic regulation", "histone acetylation"],
    "CRISPR": ["CRISPR-Cas9", "gene editing", "genome editing"],
    "organoid": ["tumor organoid", "patient-derived organoid", "3D culture model"],
    "fasting": ["caloric restriction", "dietary restriction", "intermittent fasting", "prolonged fasting"],
    "ketogenic diet": ["ketogenic", "low carbohydrate diet", "KD", "keto diet"],
}

# Normalised (lowercase-key) forward index and reverse index built at import time.
_FORWARD: dict[str, list[str]] = {k.lower(): v for k, v in ONCOLOGY_SYNONYMS.items()}
_REVERSE: dict[str, str] = {}
for _canonical, _syns in ONCOLOGY_SYNONYMS.items():
    for _s in _syns:
        _REVERSE[_s.lower()] = _canonical


def get_synonyms(term: str) -> list[str]:
    """Return synonyms for a term. Checks canonical keys and synonyms both (case-insensitive)."""
    key = term.strip().lower()
    syns = _FORWARD.get(key)
    if syns is not None:
        return syns
    canonical = _REVERSE.get(key)
    if canonical:
        return [canonical] + [s for s in ONCOLOGY_SYNONYMS[canonical] if s.lower() != key]
    return []
