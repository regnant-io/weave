// Static UI chrome strings for the SW/EN toggle (architecture 4.3): this part IS
// just translation, unlike dynamic conversation content (which is stored bilingually
// at the data layer). A production build would use next-intl; a tiny inline
// dictionary keeps the dependency surface minimal for the MVP.
import type { Language } from "./types";

type Dict = Record<string, { sw: string; en: string }>;

export const strings: Dict = {
  appTagline: {
    sw: "Kusoma na kutafiti kwa Kiswahili na Kiingereza",
    en: "Study and research in Kiswahili and English",
  },
  student: { sw: "Mwanafunzi", en: "Student" },
  researcher: { sw: "Mtafiti", en: "Researcher" },
  chooseMode: { sw: "Chagua hali yako", en: "Choose your mode" },
  studentDesc: {
    sw: "Kujifunza kwa maswali na mwongozo hatua kwa hatua.",
    en: "Learn Socratically, guided step by step.",
  },
  researcherDesc: {
    sw: "Majibu ya moja kwa moja, uchambuzi wa data na rejea sahihi.",
    en: "Direct answers, data analysis, and strict citations.",
  },
  login: { sw: "Ingia", en: "Log in" },
  register: { sw: "Jisajili", en: "Register" },
  logout: { sw: "Toka", en: "Log out" },
  projects: { sw: "Miradi", en: "Projects" },
  library: { sw: "Maktaba", en: "Library" },
  settings: { sw: "Mipangilio", en: "Settings" },
  newProject: { sw: "Mradi mpya", en: "New project" },
  chat: { sw: "Mazungumzo", en: "Chat" },
  send: { sw: "Tuma", en: "Send" },
  askPlaceholder: {
    sw: "Andika swali lako kwa Kiswahili au Kiingereza…",
    en: "Type your question in Kiswahili or English…",
  },
  liteMode: { sw: "Hali ya data ndogo", en: "Lite mode" },
  liteModeHint: {
    sw: "Chati kama picha tuli, data kidogo",
    en: "Charts as static images, less data",
  },
  phone: { sw: "Namba ya simu", en: "Phone number" },
  password: { sw: "Nywila", en: "Password" },
  email: { sw: "Barua pepe (si lazima)", en: "Email (optional)" },
  verifyOtp: { sw: "Thibitisha namba ya siri", en: "Verify OTP" },
  hypotheses: { sw: "Dhana za utafiti", en: "Hypotheses" },
  datasets: { sw: "Seti za data", en: "Datasets" },
  sources: { sw: "Vyanzo", en: "Sources" },
  open: { sw: "Wazi", en: "Open" },
  paywalled: { sw: "Inayolipiwa", en: "Paywalled" },
  predatory: { sw: "Jarida tata (hatari)", en: "Predatory (caution)" },
  searchLibrary: { sw: "Tafuta kwenye maktaba", en: "Search the library" },
  noAccount: { sw: "Huna akaunti?", en: "No account?" },
  haveAccount: { sw: "Una akaunti?", en: "Have an account?" },
  thinking: { sw: "Inafikiri…", en: "Thinking…" },
  runAnalysis: { sw: "Endesha uchambuzi", en: "Run analysis" },
};

export function t(key: string, lang: Language): string {
  const entry = strings[key];
  if (!entry) return key;
  return entry[lang];
}
