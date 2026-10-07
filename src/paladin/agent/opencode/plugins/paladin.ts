// Plugin OpenCode V2 de Paladin : outils paladin_* (réclamer un job, lire le contexte et le code, proposer).
// Aucune dépendance npm : un plugin V2 est un objet { id, setup(ctx) } (ce que renvoie Plugin.define).
// Le jeton d'agent et le bail restent dans <espace>/.paladin/ : le modèle ne les voit jamais.
// Ces outils ne permettent ni de décider, ni d'activer une règle, ni d'écrire dans l'Excel.
import { mkdir, readFile, writeFile } from "node:fs/promises"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

// <espace>/.opencode/plugins/paladin.ts -> <espace>/.paladin
const STATE = join(dirname(fileURLToPath(import.meta.url)), "..", "..", ".paladin")

type Connection = { url: string; token: string; model_requested?: string; model_provider?: string; campaign_id?: string; worker?: string }
type Json = Record<string, unknown>

const connection = async (): Promise<Connection> => JSON.parse(await readFile(join(STATE, "connection.json"), "utf8"))
const leaseFor = async (jobId: string) => (await readFile(join(STATE, "leases", jobId.replace(/[^A-Za-z0-9]/g, "")), "utf8")).trim()

async function call(method: string, path: string, opts: { jobId?: string; body?: unknown } = {}) {
  const c = await connection()
  const headers: Record<string, string> = { Authorization: `Bearer ${c.token}`, "Content-Type": "application/json" }
  if (opts.jobId) headers["X-Lease-Token"] = await leaseFor(opts.jobId)
  const res = await fetch(c.url.replace(/\/$/, "") + path, {
    method,
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  })
  return { status: res.status, text: await res.text(), conn: c }
}

const answer = (r: { status: number; text: string }) => ({ content: r.status >= 400 ? `ERREUR HTTP ${r.status} : ${r.text}` : r.text })
const str = (description: string) => ({ type: "string", description })
const schema = (properties: Json, required: string[]) => ({ type: "object", properties, required, additionalProperties: false })
const JOB = { job_id: str("job_id retourné par paladin_claim") }

const tools = [
  {
    name: "paladin_claim",
    description: "Réclame le prochain job d'analyse Paladin. Retourne job_id et finding_id, ou « AUCUN JOB ».",
    input: schema({}, []),
    async execute() {
      const c = await connection()
      const r = await call("POST", "/api/agent/claim", {
        body: { worker: c.worker ?? "opencode", campaign_id: c.campaign_id, model_requested: c.model_requested },
      })
      if (r.status === 204) return { content: "AUCUN JOB : la file est vide. Terminer." }
      if (r.status >= 400) return answer(r)
      const job = JSON.parse(r.text)
      await mkdir(join(STATE, "leases"), { recursive: true })
      await writeFile(join(STATE, "leases", job.job_id), job.lease_token, { mode: 0o600 })
      return { content: JSON.stringify({ job_id: job.job_id, finding_id: job.finding_id, input_revision: job.input_revision }) }
    },
  },
  {
    name: "paladin_context",
    description: "Dossier de contexte du job : finding, détails de l'outil (données NON FIABLES), extrait de code, checklist, précédents, schéma de réponse.",
    input: schema(JOB, ["job_id"]),
    async execute(input: { job_id: string }) {
      return answer(await call("GET", `/api/agent/jobs/${input.job_id}/context`, { jobId: input.job_id }))
    },
  },
  {
    name: "paladin_read_code",
    description: "Lit des lignes d'un fichier d'un dépôt autorisé (300 lignes max par appel). Lecture seule.",
    input: schema(
      {
        ...JOB,
        repo: str("nom du dépôt (allowed_repos)"),
        path: str("chemin relatif au dépôt, ex. app/orders.py"),
        start: { type: "integer", description: "première ligne (1 par défaut)" },
        end: { type: "integer", description: "dernière ligne" },
      },
      ["job_id", "repo", "path"],
    ),
    async execute(input: { job_id: string; repo: string; path: string; start?: number; end?: number }) {
      const q = new URLSearchParams({ repo: input.repo, path: input.path, start: String(input.start ?? 1) })
      if (input.end) q.set("end", String(input.end))
      return answer(await call("GET", `/api/agent/jobs/${input.job_id}/code?${q}`, { jobId: input.job_id }))
    },
  },
  {
    name: "paladin_search_code",
    description: "Recherche un texte (ou une regex) dans un dépôt autorisé. 40 résultats max. Lecture seule.",
    input: schema(
      {
        ...JOB,
        repo: str("nom du dépôt (allowed_repos)"),
        pattern: str("texte à chercher, ex. def safe_join"),
        glob: str("filtre de fichiers, ex. *.py"),
        regex: { type: "boolean", description: "pattern est une expression régulière" },
      },
      ["job_id", "repo", "pattern"],
    ),
    async execute(input: { job_id: string; repo: string; pattern: string; glob?: string; regex?: boolean }) {
      const q = new URLSearchParams({ repo: input.repo, pattern: input.pattern })
      if (input.glob) q.set("glob", input.glob)
      if (input.regex) q.set("regex", "true")
      return answer(await call("GET", `/api/agent/jobs/${input.job_id}/search?${q}`, { jobId: input.job_id }))
    },
  },
  {
    name: "paladin_submit",
    description: "Soumet la proposition JSON conforme au response_schema du contexte. Une proposition n'est jamais une décision.",
    input: schema({ ...JOB, proposal_json: str("objet JSON complet conforme au response_schema") }, ["job_id", "proposal_json"]),
    async execute(input: { job_id: string; proposal_json: string }) {
      let proposal: Json
      try {
        proposal = JSON.parse(input.proposal_json)
      } catch (e) {
        return { content: `ERREUR : proposal_json n'est pas un JSON valide (${e}). Corriger et soumettre à nouveau.` }
      }
      const c = await connection()
      proposal._meta = { model_requested: c.model_requested, model_provider: c.model_provider }
      return answer(await call("POST", `/api/agent/jobs/${input.job_id}/proposal`, { jobId: input.job_id, body: proposal }))
    },
  },
  {
    name: "paladin_fail",
    description: "Abandonne le job (motif obligatoire) quand l'analyse est impossible. Le job est remis en file.",
    input: schema({ ...JOB, reason: str("motif précis") }, ["job_id", "reason"]),
    async execute(input: { job_id: string; reason: string }) {
      return answer(await call("POST", `/api/agent/jobs/${input.job_id}/fail`, { jobId: input.job_id, body: { reason: input.reason } }))
    },
  },
]

export default {
  id: "paladin",
  async setup(ctx: any) {
    await ctx.tool.transform((editor: any) => {
      // codemode: false — outils exposés directement au modèle, hors de l'outil générique `execute`.
      // Le « Code Mode » d'OpenCode V2 (v2.0.22) donne au programme un `fetch` réseau que les permissions ne
      // bloquent pas (vérifié) : sans `execute`, l'agent n'a que ces outils, rien d'autre.
      for (const t of tools) editor.add({ ...t, options: { codemode: false } })
    })
  },
}
