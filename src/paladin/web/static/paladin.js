// Paladin — comportements légers de l'interface (aucune dépendance externe).
(function () {
  "use strict";
  const token = document.body.dataset.token;
  const DISCUSSION = "security appetite to be discussed";

  const help = document.getElementById("help");
  document.querySelectorAll("[data-help]").forEach((b) => b.addEventListener("click", () => help.showModal()));

  document.querySelectorAll("[data-confirm]").forEach((el) =>
    el.addEventListener("click", (e) => { if (!window.confirm(el.dataset.confirm)) e.preventDefault(); }));

  const form = document.getElementById("decision-form");
  const typing = (el) => el && (el.tagName === "TEXTAREA" || el.tagName === "SELECT" ||
    (el.tagName === "INPUT" && !["radio", "checkbox", "submit", "button"].includes(el.type)));

  // Entrée seule dans un champ texte ne valide jamais un formulaire.
  document.querySelectorAll("form input[type=text], form input[type=search]").forEach((input) => {
    if (input.type === "search") return;
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });
  });

  if (form) {
    const comment = document.getElementById("comment");
    const status = document.getElementById("draft-status");
    const discussBox = document.getElementById("discussion-box");
    const discussCheck = document.getElementById("discussion");
    const discussNote = document.getElementById("discuss-note");
    let armedReplace = false;
    let timer = null;
    let dirty = false;
    let submitting = false;

    const verdict = () => (form.querySelector("input[name=verdict]:checked") || {}).value || null;
    const sendDraft = async (keepalive) => {
      if (submitting) return;  // la décision supprime le brouillon : ne pas le recréer
      dirty = false;
      try {
        const r = await fetch(`/api/c/${form.dataset.campaign}/f/${form.dataset.finding}/draft`, {
          method: "POST", keepalive, headers: { "Content-Type": "application/json", "X-Paladin-Token": token },
          body: JSON.stringify({ verdict: verdict(), comment: comment.value, revision: form.elements.revision.value }),
        });
        status.textContent = r.ok ? "brouillon enregistré" : "brouillon non enregistré";
      } catch (_) { status.textContent = "brouillon non enregistré"; }
    };
    const saveDraft = () => { dirty = true; clearTimeout(timer); timer = setTimeout(() => sendDraft(false), 500); };
    // Navigation sans décider (lien, fermeture) : enregistrer tout de suite le brouillon en attente.
    window.addEventListener("pagehide", () => { if (dirty) { clearTimeout(timer); sendDraft(true); } });
    comment.addEventListener("input", saveDraft);
    form.querySelectorAll("input[name=verdict]").forEach((r) => r.addEventListener("change", saveDraft));

    const discuss = () => {
      const current = comment.value.trim();
      if (current && current !== DISCUSSION && !armedReplace) {
        armedReplace = true;
        discussNote.hidden = false;
      } else {
        comment.value = DISCUSSION;
        armedReplace = false;
        discussNote.hidden = true;
        saveDraft();
      }
      discussBox.hidden = false;
      discussCheck.checked = true;
    };
    document.getElementById("btn-discuss").addEventListener("click", discuss);
    const suggest = document.getElementById("btn-suggest");
    if (suggest) suggest.addEventListener("click", () => { comment.value = suggest.dataset.text; saveDraft(); });
    document.getElementById("btn-stay").addEventListener("click", () => { form.elements.next.value = "0"; });

    form.addEventListener("submit", (e) => {
      const op = e.submitter && e.submitter.value;
      if (op === "decide" && !verdict()) {
        e.preventDefault();
        window.alert("Choisir True Positive ou Not an issue — ou utiliser « À investiguer ».");
        return;
      }
      if (op === "decide") { submitting = true; clearTimeout(timer); }
      form.querySelectorAll("button").forEach((b) => { if (b !== e.submitter) b.disabled = true; }); // anti double clic
    });

    const setVerdict = (v) => { const r = form.querySelector(`input[name=verdict][value=${v}]`); r.checked = true; saveDraft(); };
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && typing(document.activeElement)) { document.activeElement.blur(); return; }
      if (typing(document.activeElement) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (help.open) return;
      // Flèches : jamais quand le focus est sur un contrôle (les radios utilisent déjà les flèches).
      if (e.key.startsWith("Arrow") && document.activeElement && document.activeElement.tagName === "INPUT") return;
      const go = (id) => { const el = document.getElementById(id); if (el) el.click(); };
      switch (e.key) {
        case "t": case "T": setVerdict("TRUE_POSITIVE"); break;
        case "n": case "N": setVerdict("NOT_AN_ISSUE"); break;
        case "a": case "A": go("btn-accept"); break;
        case "d": case "D": discuss(); break;
        case "c": case "C": e.preventDefault(); comment.focus(); break;
        case "s": case "S": case "ArrowRight": go("btn-skip"); break;
        case "ArrowLeft": go("nav-prev"); break;
        case "i": case "I": e.preventDefault(); document.getElementById("investigate").open = true; document.getElementById("inv-question").focus(); break;
        case "u": case "U": document.getElementById("undo-form").requestSubmit(); break;
        case "?": help.showModal(); break;
        default: return;
      }
    });
  } else {
    document.addEventListener("keydown", (e) => { if (e.key === "?" && !typing(document.activeElement)) help.showModal(); });
  }
})();
