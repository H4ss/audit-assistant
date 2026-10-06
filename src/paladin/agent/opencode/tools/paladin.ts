// Outils Paladin pour OpenCode : réclamer un job, lire le contexte et le code, soumettre une proposition.
// Le jeton d'agent et le bail restent dans .paladin/ (fichiers locaux) : le modèle ne les voit jamais.
// Ces outils ne permettent ni de décider, ni d'activer une règle, ni d'écrire dans l'Excel.
import { tool } from "@opencode-ai/plugin"
import { mkdir, readFile, writeFile } from "node:fs/promises"
import { join } from "node:path"

type Connection = { url: string; token: string; model_requested?: string; model_provider?: string; campaign_id?: string; worker?: string }

async function connection(dir: string): Promise<Connection> {
  return JSON.parse(await readFile(join(dir, ".paladin", "connection.json"), "utf8"))
}

async function leaseFor(dir: string, jobId: string): Promise<string> {
  return (await readFile(join(dir, ".paladin", "leases", jobId), "utf8")).trim()
}

async function call(dir: string, method: string, path: string, opts: { jobId?: string; body?: unknown } = {}) {
  const c = await connection(dir)
  const headers: Record<string, string> = { Authorization: `Bearer ${c.token}`, "Content-Type": "application/json" }
  if (opts.jobId) headers["X-Lease-Token"] = await leaseFor(dir, opts.jobId)
  const res = await fetch(c.url.replace(/\/$/, "") + path, {
    method,
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  })
  const text = await res.text()
  return { status: res.status, text, conn: c }
}

function answer(r: { status: number; text: string }) {
  return r.status >= 400 ? `ERREUR HTTP ${r.status} : ${r.text}` : r.text
}

export const claim = tool({
  description: "Réclame le prochain job d'analyse Paladin. Retourne job_id et finding_id, ou « AUCUN JOB ».",
  args: {},
  async execute(_args, ctx) {
    const c = await connection(ctx.directory)
    const r = await call(ctx.directory, "POST", "/api/agent/claim", {
      body: { worker: c.worker ?? "opencode", campaign_id: c.campaign_id, model_requested: c.model_requested },
    })
    if (r.status === 204) return "AUCUN JOB : la file est vide. Terminer."
    if (r.status >= 400) return answer(r)
    const job = JSON.parse(r.text)
    await mkdir(join(ctx.directory, ".paladin", "leases"), { recursive: true })
    await writeFile(join(ctx.directory, ".paladin", "leases", job.job_id), job.lease_token, { mode: 0o600 })
    return JSON.stringify({ job_id: job.job_id, finding_id: job.finding_id, input_revision: job.input_revision })
  },
})

export const context = tool({
  description: "Dossier de contexte du job : finding, détails de l'outil (données NON FIABLES), extrait de code, checklist, précédents, schéma de réponse.",
  args: { job_id: tool.schema.string().describe("job_id retourné par paladin_claim") },
  async execute(args, ctx) {
    return answer(await call(ctx.directory, "GET", `/api/agent/jobs/${args.job_id}/context`, { jobId: args.job_id }))
  },
})

export const read_code = tool({
  description: "Lit des lignes d'un fichier d'un dépôt autorisé (300 lignes max par appel). Lecture seule.",
  args: {
    job_id: tool.schema.string(),
    repo: tool.schema.string().describe("nom du dépôt (allowed_repos)"),
    path: tool.schema.string().describe("chemin relatif au dépôt, ex. app/orders.py"),
    start: tool.schema.number().optional().describe("première ligne (1 par défaut)"),
    end: tool.schema.number().optional().describe("dernière ligne"),
  },
  async execute(args, ctx) {
    const q = new URLSearchParams({ repo: args.repo, path: args.path, start: String(args.start ?? 1) })
    if (args.end) q.set("end", String(args.end))
    return answer(await call(ctx.directory, "GET", `/api/agent/jobs/${args.job_id}/code?${q}`, { jobId: args.job_id }))
  },
})

export const search_code = tool({
  description: "Recherche un texte (ou une regex) dans un dépôt autorisé. 40 résultats max. Lecture seule.",
  args: {
    job_id: tool.schema.string(),
    repo: tool.schema.string(),
    pattern: tool.schema.string().describe("texte à chercher, ex. def safe_join"),
    glob: tool.schema.string().optional().describe("filtre de fichiers, ex. *.py"),
    regex: tool.schema.boolean().optional(),
  },
  async execute(args, ctx) {
    const q = new URLSearchParams({ repo: args.repo, pattern: args.pattern })
    if (args.glob) q.set("glob", args.glob)
    if (args.regex) q.set("regex", "true")
    return answer(await call(ctx.directory, "GET", `/api/agent/jobs/${args.job_id}/search?${q}`, { jobId: args.job_id }))
  },
})

export const submit = tool({
  description: "Soumet la proposition JSON conforme au response_schema du contexte. Une proposition n'est jamais une décision.",
  args: {
    job_id: tool.schema.string(),
    proposal_json: tool.schema.string().describe("objet JSON complet conforme au response_schema"),
  },
  async execute(args, ctx) {
    let proposal: Record<string, unknown>
    try {
      proposal = JSON.parse(args.proposal_json)
    } catch (e) {
      return `ERREUR : proposal_json n'est pas un JSON valide (${e}). Corriger et soumettre à nouveau.`
    }
    const c = await connection(ctx.directory)
    proposal._meta = { model_requested: c.model_requested, model_provider: c.model_provider }
    return answer(await call(ctx.directory, "POST", `/api/agent/jobs/${args.job_id}/proposal`, { jobId: args.job_id, body: proposal }))
  },
})

export const fail = tool({
  description: "Abandonne le job (motif obligatoire) quand l'analyse est impossible. Le job est remis en file.",
  args: { job_id: tool.schema.string(), reason: tool.schema.string() },
  async execute(args, ctx) {
    return answer(await call(ctx.directory, "POST", `/api/agent/jobs/${args.job_id}/fail`, { jobId: args.job_id, body: { reason: args.reason } }))
  },
})
