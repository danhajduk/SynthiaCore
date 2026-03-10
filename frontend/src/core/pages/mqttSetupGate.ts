export type MqttSetupSummaryLike = {
  setup?: {
    requires_setup?: boolean;
    setup_complete?: boolean;
  } | null;
} | null | undefined;

const SETUP_ONLY_SECTION = "setup";
const DEFAULT_SECTION = "overview";

export function resolveMqttSetupSection(
  requestedSection: string | null | undefined,
  setupSummary: MqttSetupSummaryLike,
): { section: string; redirected: boolean; gateActive: boolean } {
  const raw = String(requestedSection || "").trim().toLowerCase();
  const section = raw || DEFAULT_SECTION;
  const requiresSetup = Boolean(setupSummary?.setup?.requires_setup);
  const setupComplete = Boolean(setupSummary?.setup?.setup_complete);
  const gateActive = requiresSetup && !setupComplete;
  if (gateActive && section !== SETUP_ONLY_SECTION) {
    return { section: SETUP_ONLY_SECTION, redirected: true, gateActive: true };
  }
  return { section, redirected: false, gateActive };
}
