/**
 * Oracle "products & services" sourcing for NodeDetail.
 *
 * Each oracle exposes an AI-Market v2 manifest at `<base>/ai-market/v2/manifest`
 * returning `{ tools: [{ capability_id, description, price_per_call_usd, product_id }] }`.
 * Several oracles share the family app, so the manifest aggregates tools across
 * products — we filter to the ones whose `product_id === "prod-<slug>"`.
 *
 * The monitor only carries each oracle's *scene* URL on the node (e.g.
 * `https://oracles.modelmarket.dev/?o=platon`). We derive the manifest base from
 * that origin using the same path mapping the backend uses (oracle_family.py:
 * oracle_live_url): root for platon, `/chronos`, `/<slug>` for the physics
 * oracles, `/family` for the remaining family members.
 *
 * Everything here is best-effort: failures resolve to `null` so NodeDetail can
 * fall back to the capability data already present on the node.
 */

export interface OracleTool {
  capability_id: string;
  description?: string;
  price_per_call_usd?: number;
  product_id?: string;
  name?: string;
}

interface ManifestResponse {
  tools?: OracleTool[];
  description?: string;
}

export interface OracleManifest {
  tools: OracleTool[];
  /** Oracle-level prose description from the manifest, when the endpoint provides one. */
  description?: string;
}

// Oracles served via the shared family app rather than their own path.
const FAMILY_SLUGS = new Set(['lattice', 'murmuration', 'lumen', 'colony', 'turing']);
// Physics oracles + advanced oracles reachable at `/<slug>`.
const OWN_PATH_SLUGS = new Set([
  'ablation',
  'fermat',
  'landauer',
  'percola',
  'chronos',
]);

/** Extract the oracle slug from a node id ("oracle-platon" -> "platon"). */
export function slugFromNodeId(nodeId: string): string {
  return nodeId.replace(/^oracle-/, '');
}

/**
 * Build the AI-Market manifest URL from a node's scene URL.
 * Returns null when no usable origin can be derived.
 */
export function manifestUrlFromScene(sceneUrl: string | undefined, slug: string): string | null {
  if (!sceneUrl) return null;
  let origin: string;
  try {
    origin = new URL(sceneUrl).origin;
  } catch {
    return null;
  }
  let path = '';
  if (slug === 'platon') {
    path = '';
  } else if (OWN_PATH_SLUGS.has(slug)) {
    path = `/${slug}`;
  } else if (FAMILY_SLUGS.has(slug)) {
    path = '/family';
  } else {
    // Advanced oracles (sortes, gauss, aestus, betti, kantor, fourier) are also
    // served through the family app today.
    path = '/family';
  }
  return `${origin}${path}/ai-market/v2/manifest`;
}

// Cache one in-flight/resolved promise per manifest URL so multiple panels and
// re-opens never refetch the same manifest.
const cache = new Map<string, Promise<ManifestResponse | null>>();

async function fetchManifest(url: string): Promise<ManifestResponse | null> {
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 4000);
    const res = await fetch(url, { signal: ctrl.signal, headers: { Accept: 'application/json' } });
    clearTimeout(timer);
    if (!res.ok) return null;
    const body = (await res.json()) as ManifestResponse;
    if (!body || !Array.isArray(body.tools)) return null;
    return body;
  } catch {
    return null;
  }
}

/**
 * Fetch the products & services for one oracle (cached). Resolves to the tools
 * whose product_id matches this oracle (plus any oracle-level description), or
 * null when the manifest is unreachable / doesn't know this slug.
 */
export function fetchOracleTools(
  sceneUrl: string | undefined,
  slug: string,
): Promise<OracleManifest | null> {
  const url = manifestUrlFromScene(sceneUrl, slug);
  if (!url) return Promise.resolve(null);
  let pending = cache.get(url);
  if (!pending) {
    pending = fetchManifest(url);
    cache.set(url, pending);
  }
  const productId = `prod-${slug}`;
  return pending.then((body) => {
    if (!body || !Array.isArray(body.tools)) return null;
    const mine = body.tools.filter((t) => !t.product_id || t.product_id === productId);
    // A shared family manifest carries every product's tools; if filtering by
    // product_id leaves nothing, the manifest just doesn't know this slug.
    if (!mine.length) return null;
    return { tools: mine, description: body.description };
  });
}

/**
 * Parse the capability ids embedded in a node's description string, e.g.
 *   "Robust consensus aggregation · caps: murmuration.aggregate@v1"
 * Returns the raw "id@vN" tokens (possibly empty).
 */
export function parseCapsFromDescription(description: string | undefined): string[] {
  if (!description) return [];
  const m = description.match(/caps:\s*(.+)$/i);
  if (!m) return [];
  return m[1]
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Strip the "· caps: …" suffix to get the human description / skill line. */
export function descriptionWithoutCaps(description: string | undefined): string {
  if (!description) return '';
  return description.replace(/\s*·?\s*caps:\s*.+$/i, '').trim();
}
