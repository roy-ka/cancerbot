/**
 * Content for the chat-page icon tutorial (IconGuideDialog).
 *
 * Data only, so it can be unit-tested without a DOM. The matching icon for each
 * `key` is rendered by IconGuideDialog, which maps keys to the *same* icon
 * components the real UI uses — a `Record<IconKey, ...>` there, so TypeScript
 * fails the build if an entry ever lacks an icon.
 */

export type IconKey =
  | 'account'
  | 'logout'
  | 'healthProfile'
  | 'changeEmail'
  | 'deleteAccount'
  | 'findTrials'
  | 'privacy'
  | 'about'
  | 'guide'
  | 'feedback'
  | 'closeSidebar'
  | 'toggleSidebar'
  | 'deleteConversation'
  | 'translate'
  | 'trialBadge'
  | 'citation'
  | 'send'

export type GuideArea = 'Sidebar' | 'Conversations' | 'Answers' | 'Writing'

export type GuideEntry = {
  key: IconKey
  label: string
  /** One short line — this is a brief, not documentation. */
  description: string
  area: GuideArea
  /** Rendered instead of an icon component (the UI uses an emoji here too). */
  emoji?: string
  /** Only visible on small screens, where the sidebar collapses. */
  smallScreenOnly?: boolean
}

export const GUIDE_AREAS: GuideArea[] = [
  'Sidebar',
  'Conversations',
  'Answers',
  'Writing',
]

export const GUIDE_ENTRIES: GuideEntry[] = [
  // --- Sidebar -------------------------------------------------------------
  {
    key: 'account',
    label: 'Account',
    description: 'Your account menu.',
    area: 'Sidebar',
  },
  {
    key: 'logout',
    label: 'Logout',
    description: 'Sign out of CancerBot. Inside the account menu.',
    area: 'Sidebar',
  },
  {
    key: 'healthProfile',
    label: 'Health Profile',
    description:
      'Optional details (cancer type, stage, biomarkers) to tailor answers. Inside the account menu.',
    area: 'Sidebar',
  },
  {
    key: 'changeEmail',
    label: 'Change Email',
    description: 'Update your login email. Inside the account menu.',
    area: 'Sidebar',
  },
  {
    key: 'deleteAccount',
    label: 'Delete account',
    description:
      'Starts account deletion, with a 7-day window to cancel. Inside the account menu.',
    area: 'Sidebar',
  },
  {
    key: 'findTrials',
    label: 'Find trials to join',
    description:
      'Search ClinicalTrials.gov for trials that are currently recruiting.',
    area: 'Sidebar',
  },
  {
    key: 'privacy',
    label: 'Privacy',
    description: 'Opens the privacy policy in a new tab.',
    area: 'Sidebar',
  },
  {
    key: 'about',
    label: 'About',
    description: 'What CancerBot is and what it can do.',
    area: 'Sidebar',
  },
  {
    key: 'guide',
    label: 'This guide',
    description: 'Reopen this icon guide at any time.',
    area: 'Sidebar',
  },
  {
    key: 'feedback',
    label: 'Report a bug or send feedback',
    description: 'Report something broken, or share your thoughts on CancerBot.',
    area: 'Sidebar',
  },
  {
    key: 'closeSidebar',
    label: 'Close the sidebar',
    description: 'Hides the conversation list.',
    area: 'Sidebar',
    emoji: '✕',
    smallScreenOnly: true,
  },

  // --- Conversations -------------------------------------------------------
  {
    key: 'toggleSidebar',
    label: 'Conversations',
    description: 'Show or hide your list of conversations.',
    area: 'Conversations',
    emoji: '☰',
    smallScreenOnly: true,
  },
  {
    key: 'deleteConversation',
    label: 'Delete conversation',
    description: 'Removes that conversation from your list.',
    area: 'Conversations',
  },

  // --- Answers -------------------------------------------------------------
  {
    key: 'citation',
    label: 'pmid: / doi: / wiki:',
    description:
      'A cited source. Hover to preview the excerpt, click to keep it open and get the link.',
    area: 'Answers',
  },
  {
    key: 'trialBadge',
    label: 'Trial badge',
    description:
      'That source is a clinical-trial registration, not a published paper.',
    area: 'Answers',
  },
  {
    key: 'translate',
    label: 'Translate',
    description: "Opens that answer in Google Translate, in your browser's language.",
    area: 'Answers',
  },

  // --- Writing -------------------------------------------------------------
  {
    key: 'send',
    label: 'Send',
    description: 'Sends your question. Enter sends, Shift+Enter adds a line.',
    area: 'Writing',
    emoji: '🦀',
  },
]

/** Entries for one area, in declaration order. */
export function entriesForArea(area: GuideArea): GuideEntry[] {
  return GUIDE_ENTRIES.filter((e) => e.area === area)
}
