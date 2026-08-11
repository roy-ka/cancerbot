/**
 * Copy + example prompts for the new-conversation intro (ConversationIntro).
 *
 * The intro leads with a constant explanation that this is a RAG system, then
 * shows a random handful of example prompts so a fresh conversation always
 * suggests something specific to ask. Kept here (pure data + a pure picker) so
 * it's unit-testable without a DOM.
 */

/** Shown in the popup behind the "RAG" link in the intro message. */
export const RAG_EXPLAINER =
  'Retrieval-Augmented Generation: instead of answering from memory alone, ' +
  'CancerBot searches trusted medical sources — PubMed, CrossRef, Wikipedia and ' +
  'ClinicalTrials.gov — live for every question, then answers grounded in what ' +
  'it retrieves and cites those sources. Because each answer is built from the ' +
  'evidence it finds, the more specific your question — naming the cancer type, ' +
  'drug, gene or trial — the better the sources it can retrieve.'

/**
 * Pool of example prompts. Deliberately broad (metabolism, targeted therapy,
 * immunotherapy, drug repurposing, trials, prognosis) so the random sample
 * feels different each time. Includes the Warburg effect, metabolic pathways
 * and trial-finding among others.
 */
export const INTRO_TIPS: string[] = [
  'How does the Warburg effect drive tumor growth in glioblastoma?',
  'Which metabolic pathways are most altered in pancreatic cancer?',
  'Help me find completed clinical trials of metformin in breast cancer',
  'What is the evidence for repurposing mebendazole in glioblastoma?',
  'How do EGFR mutations change treatment options in non-small cell lung cancer?',
  'Compare FOLFIRINOX and gemcitabine for metastatic pancreatic cancer',
  'What role does the PI3K/AKT/mTOR pathway play in breast cancer drug resistance?',
  'Summarize recent immunotherapy trial results for advanced melanoma',
  'How does a ketogenic diet interact with standard chemotherapy?',
  'What are the mechanisms of tamoxifen resistance in ER-positive breast cancer?',
  'Explain the role of glutamine metabolism in proliferating cancer cells',
  'What targeted therapies exist for BRAF V600E mutated colorectal cancer?',
  'How effective is repurposed disulfiram as an anticancer agent?',
  'What is the prognosis for IDH-mutant versus wild-type gliomas?',
  'Which biomarkers predict response to PD-1 checkpoint inhibitors?',
  'How does the tumor microenvironment influence metastasis?',
  'Which clinical trials are studying CAR-T therapy for solid tumors?',
  'Explain the link between obesity, insulin signaling and colorectal cancer risk',
  'What is the evidence for high-dose vitamin C as an adjunct cancer therapy?',
  'How do HER2-targeted therapies work in gastric cancer?',
  'What metabolic vulnerabilities can be targeted in triple-negative breast cancer?',
]

/** How many example prompts to surface per new conversation. */
export const MIN_TIPS = 4
export const MAX_TIPS = 5

/**
 * Pick a random 4–5 unique prompts from `all`. `rng` is injectable so the
 * selection is deterministic under test. Never returns more than `all` holds.
 */
export function pickTips(
  all: string[] = INTRO_TIPS,
  rng: () => number = Math.random,
): string[] {
  const span = MAX_TIPS - MIN_TIPS + 1
  const count = Math.min(all.length, MIN_TIPS + Math.floor(rng() * span))
  const pool = [...all]
  const chosen: string[] = []
  while (chosen.length < count && pool.length > 0) {
    const idx = Math.floor(rng() * pool.length)
    chosen.push(pool.splice(idx, 1)[0])
  }
  return chosen
}
