// Meisterli-Chat: Verlauf per Polling, Senden per POST, Aufnahme mit MediaRecorder. Kein Framework.
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);

const verlauf = $("#verlauf");
const liste = $("#nachrichten");
const tippt = $("#tippt");
const status = $("#status");
const text = $("#text");
const sendenKnopf = $("#senden");
const datei = $("#datei");

let letzteId = 0;
let gespraechId = null;
let schreibt = false;
let pollTimer = null;
let schnellBis = 0; // nach dem Senden eine Weile schneller nachfragen
const elemente = new Map(); // id → {el, json, n}
const offeneAudios = new Set(); // Audio-Nachrichten, deren Transkript noch fehlt

// ---------------------------------------------------------------------------
// Hilfen
// ---------------------------------------------------------------------------

function el(tag, klasse, inhalt) {
  const e = document.createElement(tag);
  if (klasse) e.className = klasse;
  if (inhalt !== undefined && inhalt !== null) e.textContent = inhalt;
  return e;
}

function svg(markup, klasse) {
  const span = el("span", klasse);
  span.innerHTML = markup; // nur feste Symbole aus diesem Skript, nie Nutzertext
  return span.firstElementChild;
}

const SYMBOLE = {
  haken: '<svg class="haken" viewBox="0 0 16 11"><path d="M1 6l3 3 6-7M6 8.5 7 9.5l6-7.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  play: '<svg viewBox="0 0 24 24" width="28" height="28"><path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/></svg>',
  pause: '<svg viewBox="0 0 24 24" width="28" height="28"><rect x="7" y="5" width="3.6" height="14" rx="1" fill="currentColor"/><rect x="13.4" y="5" width="3.6" height="14" rx="1" fill="currentColor"/></svg>',
  pdf: '<svg class="dok-icon" viewBox="0 0 30 36"><path d="M3 0h17l10 10v23a3 3 0 0 1-3 3H3a3 3 0 0 1-3-3V3a3 3 0 0 1 3-3z" fill="#e5484d"/><path d="M20 0v7a3 3 0 0 0 3 3h7z" fill="#f59ea1"/><text x="15" y="27" font-family="Arial, sans-serif" font-size="8.5" font-weight="700" fill="#fff" text-anchor="middle">PDF</text></svg>',
};

function uhrzeit(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString("de-CH", { hour: "2-digit", minute: "2-digit" });
}

function tagText(iso) {
  const d = new Date(iso);
  const heute = new Date();
  const gestern = new Date(Date.now() - 864e5);
  if (d.toDateString() === heute.toDateString()) return "Heute";
  if (d.toDateString() === gestern.toDateString()) return "Gestern";
  return d.toLocaleDateString("de-CH");
}

function mmss(sekunden) {
  if (!isFinite(sekunden) || sekunden < 0) return "0:00";
  const s = Math.round(sekunden);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function toast(meldung) {
  const t = el("div", "toast", meldung);
  $("#handy").appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

function amEnde() {
  return verlauf.scrollHeight - verlauf.scrollTop - verlauf.clientHeight < 120;
}

function nachUnten() {
  verlauf.scrollTop = verlauf.scrollHeight;
}

// ---------------------------------------------------------------------------
// Darstellung der Nachrichten
// ---------------------------------------------------------------------------

function meta(n) {
  const m = el("span", "meta");
  m.appendChild(el("span", "", uhrzeit(n.zeit)));
  if (n.absender === "ich") m.appendChild(svg(SYMBOLE.haken));
  return m;
}

function blase(n, klasse = "") {
  const b = el("div", `blase ${n.absender} ${klasse}`);
  if (n.inhalt && n.inhalt.fehler) b.classList.add("fehler");
  return b;
}

function textBlase(n) {
  const b = blase(n);
  b.appendChild(el("span", "text", n.inhalt.text));
  b.appendChild(meta(n));
  return [b];
}

// Sprachnachricht ---------------------------------------------------------

const player = new Audio();
let spielendeId = null;
const wellenCache = new Map();

function pseudoWelle(id, anzahl) {
  let x = (id * 9301 + 49297) % 233280;
  return Array.from({ length: anzahl }, () => {
    x = (x * 9301 + 49297) % 233280;
    return 0.25 + 0.75 * (x / 233280);
  });
}

async function echteWelle(url, anzahl) {
  const antwort = await fetch(url);
  const puffer = await antwort.arrayBuffer();
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const audio = await ctx.decodeAudioData(puffer);
  ctx.close();
  const daten = audio.getChannelData(0);
  const block = Math.floor(daten.length / anzahl) || 1;
  const spitzen = [];
  for (let i = 0; i < anzahl; i++) {
    let max = 0;
    for (let j = i * block; j < Math.min((i + 1) * block, daten.length); j += 16) {
      max = Math.max(max, Math.abs(daten[j]));
    }
    spitzen.push(max);
  }
  const hoechste = Math.max(...spitzen, 0.01);
  return { spitzen: spitzen.map((s) => 0.18 + 0.82 * (s / hoechste)), dauer: audio.duration };
}

function sprachBlase(n) {
  const b = blase(n);
  const url = `/api/chat/audio/${n.id}`;
  const zeile = el("div", "sprach");
  const play = el("button", "play");
  play.type = "button";
  play.setAttribute("aria-label", "Abspielen");
  play.appendChild(svg(SYMBOLE.play));
  const welle = el("div", "welle");
  const anzahl = 34;
  const zeichne = (werte) => {
    welle.innerHTML = "";
    werte.forEach((w) => {
      const i = el("i");
      i.style.height = `${Math.round(w * 100)}%`;
      welle.appendChild(i);
    });
  };
  zeichne(pseudoWelle(n.id, anzahl));
  zeile.append(play, welle);

  const unten = el("div", "sprach-meta");
  const dauerText = el("span", "", mmss(n.inhalt.dauer));
  unten.append(dauerText, meta(n));
  b.append(zeile, unten);

  const ladeWelle = () => {
    if (!wellenCache.has(n.id)) wellenCache.set(n.id, echteWelle(url, anzahl).catch(() => null));
    wellenCache.get(n.id).then((w) => {
      if (!w) return;
      zeichne(w.spitzen);
      if (!n.inhalt.dauer) dauerText.textContent = mmss(w.dauer);
    });
  };
  ladeWelle();

  const fortschritt = () => {
    if (spielendeId !== n.id) return;
    const anteil = player.duration ? player.currentTime / player.duration : 0;
    Array.from(welle.children).forEach((balken, i) => balken.classList.toggle("gespielt", i / anzahl < anteil));
    dauerText.textContent = mmss(player.currentTime);
  };

  play.addEventListener("click", () => {
    if (spielendeId === n.id && !player.paused) {
      player.pause();
      return;
    }
    if (spielendeId !== n.id) {
      player.src = url;
      spielendeId = n.id;
    }
    player.play().catch((e) => toast("Abspielen nicht möglich: " + e.message));
  });
  welle.addEventListener("click", (ev) => {
    if (spielendeId !== n.id || !player.duration) return;
    const r = welle.getBoundingClientRect();
    player.currentTime = ((ev.clientX - r.left) / r.width) * player.duration;
  });
  player.addEventListener("timeupdate", fortschritt);
  const symbol = () => {
    const spielt = spielendeId === n.id && !player.paused;
    play.innerHTML = "";
    play.appendChild(svg(spielt ? SYMBOLE.pause : SYMBOLE.play));
  };
  player.addEventListener("play", symbol);
  player.addEventListener("pause", symbol);
  player.addEventListener("ended", () => {
    if (spielendeId !== n.id) return;
    Array.from(welle.children).forEach((balken) => balken.classList.remove("gespielt"));
    dauerText.textContent = mmss(n.inhalt.dauer || player.duration);
  });

  const transkript = el("div", "transkript");
  if (n.inhalt.status === "transkribiere") {
    transkript.textContent = "Transkribiere …";
  } else if (n.inhalt.status === "fehler") {
    transkript.textContent = "Transkription fehlgeschlagen";
  } else if (n.inhalt.transkript) {
    transkript.textContent = n.inhalt.transkript;
    if (n.inhalt.dauer_transkription != null) {
      transkript.appendChild(el("span", "dauer", ` · ${n.inhalt.dauer_transkription.toFixed(1)} s`));
    }
  }
  return [b, transkript];
}

// Zusammenfassung ---------------------------------------------------------

function zusammenfassungBlase(n) {
  const z = n.inhalt;
  const b = blase(n, "zusammenfassung");
  b.appendChild(el("div", "zf-titel", `🧾 Rechnung für ${z.kunde.name}`));
  const adresse = el("div", "zf-adresse", `${z.kunde.strasse}, ${z.kunde.plz} ${z.kunde.ort} `);
  if (z.kunde.gespeichert) adresse.appendChild(el("span", "gespeichert", "(gespeichert)"));
  b.appendChild(adresse);

  const tabelle = el("table", "zf-positionen");
  z.positionen.forEach((p) => {
    const tr = el("tr");
    const links = el("td");
    links.appendChild(el("div", "", p.beschreibung));
    const detail = el("div", "detail", `${p.menge} ${p.einheit} à ${p.preis} `);
    if (p.gespeichert) detail.appendChild(el("span", "gespeichert", "(gespeichert)"));
    links.appendChild(detail);
    tr.append(links, el("td", "betrag", p.betrag));
    tabelle.appendChild(tr);
  });
  b.appendChild(tabelle);

  const summen = el("table", "zf-summen");
  const zeile = (a, bb, klasse) => {
    const tr = el("tr", klasse || "");
    tr.append(el("td", "", a), el("td", "", bb));
    summen.appendChild(tr);
  };
  if (z.mwst_pflichtig) {
    zeile("Netto", z.netto);
    zeile(`MWST ${z.mwst_satz} %`, z.mwst);
  }
  zeile("Total CHF", z.total, "total");
  b.appendChild(summen);
  const datum = z.leistungsdatum_heute ? `Leistungsdatum: heute (${z.leistungsdatum})` : `Leistungsdatum: ${z.leistungsdatum}`;
  b.appendChild(el("div", "zf-datum", datum));
  b.appendChild(meta(n));

  const knoepfe = el("div", "knoepfe");
  (z.knoepfe || []).forEach((label) => {
    const k = el("button", "", label);
    k.type = "button";
    k.dataset.antwort = label;
    k.disabled = true;
    k.addEventListener("click", () => {
      document.querySelectorAll(".knoepfe button").forEach((x) => (x.disabled = true));
      sende({ text: label });
    });
    knoepfe.appendChild(k);
  });
  return [b, knoepfe];
}

// Dokument ------------------------------------------------------------------

function pdfBlase(n) {
  const d = n.inhalt;
  const b = blase(n);
  const a = el("a", "dokument");
  a.href = `/api/chat/pdf/${d.rechnung_id}`;
  a.target = "_blank";
  a.rel = "noopener";
  const kopf = el("div", "dok-kopf");
  kopf.appendChild(svg(SYMBOLE.pdf));
  const info = el("div");
  info.style.minWidth = "0";
  info.appendChild(el("div", "dok-name", d.dateiname));
  const seiten = d.seiten === 1 ? "1 Seite" : `${d.seiten} Seiten`;
  info.appendChild(el("div", "dok-info", `${seiten} · PDF · ${d.groesse_kb} kB`));
  kopf.appendChild(info);
  a.appendChild(kopf);
  b.appendChild(a);
  b.appendChild(meta(n));
  return [b];
}

function baue(n) {
  switch (n.typ) {
    case "audio":
      return sprachBlase(n);
    case "zusammenfassung":
      return zusammenfassungBlase(n);
    case "pdf":
      return pdfBlase(n);
    default:
      return textBlase(n);
  }
}

let letzterTag = null;
let letzterAbsender = null;

function fuegeEin(n) {
  const tag = tagText(n.zeit);
  if (tag !== letzterTag) {
    liste.appendChild(el("div", "datum", tag));
    letzterTag = tag;
    letzterAbsender = null;
  }
  const zeile = el("div", n.absender === "ich" ? "zeile-rechts" : "zeile-links");
  if (letzterAbsender === n.absender) zeile.classList.add("folgend");
  letzterAbsender = n.absender;
  baue(n).forEach((teil) => zeile.appendChild(teil));
  liste.appendChild(zeile);
  elemente.set(n.id, { el: zeile, json: JSON.stringify(n.inhalt), n });
}

function ersetze(n) {
  const alt = elemente.get(n.id);
  const neu = el("div", alt.el.className);
  baue(n).forEach((teil) => neu.appendChild(teil));
  alt.el.replaceWith(neu);
  elemente.set(n.id, { el: neu, json: JSON.stringify(n.inhalt), n });
}

function aktualisiereHaken() {
  let hoechsteAntwort = 0;
  elemente.forEach(({ n }) => {
    if (n.absender === "meisterli") hoechsteAntwort = Math.max(hoechsteAntwort, n.id);
  });
  elemente.forEach(({ el: e, n }) => {
    if (n.absender !== "ich") return;
    e.querySelectorAll(".haken").forEach((h) => h.classList.toggle("gelesen", n.id < hoechsteAntwort));
  });
}

function aktualisiereKnoepfe(aktivId) {
  elemente.forEach(({ el: e, n }) => {
    e.querySelectorAll(".knoepfe button").forEach((k) => (k.disabled = n.id !== aktivId));
  });
}

function setzeSchreibt(wert) {
  schreibt = wert;
  tippt.hidden = !wert;
  status.textContent = wert ? "schreibt…" : "online";
  status.classList.toggle("schreibt", wert);
}

function leereAnzeige() {
  liste.innerHTML = "";
  elemente.clear();
  offeneAudios.clear();
  letzteId = 0;
  letzterTag = null;
  letzterAbsender = null;
}

// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------

async function holen() {
  clearTimeout(pollTimer);
  try {
    const nach = offeneAudios.size ? Math.min(...offeneAudios) - 1 : letzteId;
    const antwort = await fetch(`/api/chat/verlauf?nach=${nach}`);
    const d = await antwort.json();
    if ((gespraechId !== null && d.gespraech_id !== gespraechId) || d.letzte_id < letzteId) {
      leereAnzeige(); // Chat wurde anderswo geleert oder zurückgesetzt
      gespraechId = d.gespraech_id;
      return holen();
    }
    gespraechId = d.gespraech_id;
    const unten = amEnde();
    let neu = false;
    d.nachrichten.forEach((n) => {
      if (elemente.has(n.id)) {
        if (elemente.get(n.id).json !== JSON.stringify(n.inhalt)) ersetze(n);
      } else {
        fuegeEin(n);
        neu = true;
      }
      if (n.typ === "audio" && n.inhalt.status === "transkribiere") offeneAudios.add(n.id);
      else offeneAudios.delete(n.id);
      letzteId = Math.max(letzteId, n.id);
    });
    setzeSchreibt(d.schreibt);
    aktualisiereHaken();
    aktualisiereKnoepfe(d.aktive_knoepfe);
    if ((neu && unten) || (neu && schnellBis > Date.now()) || d.schreibt) nachUnten();
  } catch (e) {
    status.textContent = "keine Verbindung";
  }
  const schnell = schreibt || Date.now() < schnellBis;
  pollTimer = setTimeout(holen, schnell ? 600 : 3000);
}

// ---------------------------------------------------------------------------
// Senden
// ---------------------------------------------------------------------------

async function sende({ text: t, blob, name, dauer }) {
  const daten = new FormData();
  if (t) daten.append("text", t);
  if (blob) daten.append("audio", blob, name);
  if (dauer) daten.append("dauer", String(Math.round(dauer * 10) / 10));
  sendenKnopf.disabled = true;
  try {
    const antwort = await fetch("/api/chat/senden", { method: "POST", body: daten });
    if (!antwort.ok) {
      const j = await antwort.json().catch(() => ({}));
      toast(j.fehler || "Senden fehlgeschlagen.");
      return;
    }
    schnellBis = Date.now() + 4000;
    setzeSchreibt(true);
    await holen();
    nachUnten();
  } catch (e) {
    toast("Server nicht erreichbar.");
  } finally {
    sendenKnopf.disabled = false;
  }
}

function sendeText() {
  const t = text.value.trim();
  if (!t) return;
  text.value = "";
  passeFeldAn();
  sende({ text: t });
}

function passeFeldAn() {
  text.style.height = "auto";
  text.style.height = Math.min(text.scrollHeight, 120) + "px";
  if (!aufnahme) sendenKnopf.classList.toggle("text", text.value.trim().length > 0);
  sendenKnopf.setAttribute("aria-label", text.value.trim() ? "Senden" : "Aufnehmen");
}

text.addEventListener("input", passeFeldAn);
text.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
    ev.preventDefault();
    sendeText();
  }
});

// Aufnahme: Antippen startet, erneutes Antippen sendet, Papierkorb verwirft.
let aufnahme = null; // {recorder, stream, teile, start, timer, endung, verwerfen}

function mimeTyp() {
  const kandidaten = [
    ["audio/webm;codecs=opus", ".webm"],
    ["audio/mp4", ".m4a"],
    ["audio/ogg;codecs=opus", ".ogg"],
    ["audio/webm", ".webm"],
  ];
  for (const [typ, endung] of kandidaten) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(typ)) return [typ, endung];
  }
  return ["", ".webm"];
}

function zeigeAufnahme(an) {
  $("#feld-normal").hidden = an;
  $("#feld-aufnahme").hidden = !an;
  sendenKnopf.classList.toggle("aufnahme", an);
  sendenKnopf.setAttribute("aria-label", an ? "Sprachnachricht senden" : "Aufnehmen");
  if (!an) passeFeldAn();
}

async function starteAufnahme() {
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    toast("Aufnehmen geht hier nicht (nur über HTTPS oder localhost). Nimm die Büroklammer.");
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    toast("Kein Zugriff auf das Mikrofon.");
    return;
  }
  const [typ, endung] = mimeTyp();
  const recorder = new MediaRecorder(stream, typ ? { mimeType: typ } : undefined);
  const a = { recorder, stream, teile: [], start: Date.now(), endung, verwerfen: false };
  recorder.ondataavailable = (e) => e.data.size && a.teile.push(e.data);
  recorder.onstop = () => {
    stream.getTracks().forEach((t) => t.stop());
    clearInterval(a.timer);
    aufnahme = null;
    zeigeAufnahme(false);
    if (a.verwerfen) return;
    const dauer = (Date.now() - a.start) / 1000;
    if (dauer < 0.6) {
      toast("Zu kurz – tippe, sprich, und tippe nochmals zum Senden.");
      return;
    }
    const blob = new Blob(a.teile, { type: recorder.mimeType || typ });
    sende({ blob, name: "sprachnachricht" + endung, dauer });
  };
  a.timer = setInterval(() => ($("#laufzeit").textContent = mmss((Date.now() - a.start) / 1000)), 250);
  $("#laufzeit").textContent = "0:00";
  recorder.start();
  aufnahme = a;
  zeigeAufnahme(true);
}

sendenKnopf.addEventListener("click", () => {
  if (aufnahme) {
    aufnahme.recorder.stop();
  } else if (text.value.trim()) {
    sendeText();
  } else {
    starteAufnahme();
  }
});

$("#abbrechen").addEventListener("click", () => {
  if (!aufnahme) return;
  aufnahme.verwerfen = true;
  aufnahme.recorder.stop();
});

// Büroklammer: Audiodatei hochladen
$("#anhang").addEventListener("click", () => datei.click());

function audioDauer(file) {
  return new Promise((resolve) => {
    const a = new Audio();
    const url = URL.createObjectURL(file);
    const fertig = (wert) => {
      URL.revokeObjectURL(url);
      resolve(wert);
    };
    a.preload = "metadata";
    a.onloadedmetadata = () => fertig(isFinite(a.duration) ? a.duration : null);
    a.onerror = () => fertig(null);
    setTimeout(() => fertig(null), 3000);
    a.src = url;
  });
}

datei.addEventListener("change", async () => {
  const file = datei.files[0];
  datei.value = "";
  if (!file) return;
  const dauer = await audioDauer(file);
  sende({ blob: file, name: file.name, dauer });
});

// ---------------------------------------------------------------------------
// Menü
// ---------------------------------------------------------------------------

const menue = $("#menue");
const menueKnopf = $("#menue-knopf");
menueKnopf.addEventListener("click", (ev) => {
  ev.stopPropagation();
  menue.hidden = !menue.hidden;
  menueKnopf.setAttribute("aria-expanded", String(!menue.hidden));
});
document.addEventListener("click", (ev) => {
  if (!menue.hidden && !menue.contains(ev.target)) menue.hidden = true;
});

menue.addEventListener("click", async (ev) => {
  const aktion = ev.target.dataset && ev.target.dataset.aktion;
  if (!aktion) return;
  menue.hidden = true;
  const frage =
    aktion === "leeren"
      ? "Chat leeren? Das Gedächtnis bleibt erhalten."
      : "Alles zurücksetzen? Chat, Gedächtnis und Kunden werden gelöscht. Firmendaten und Rechnungen bleiben.";
  if (!confirm(frage)) return;
  await fetch(`/api/chat/${aktion}`, { method: "POST" });
  leereAnzeige();
  gespraechId = null;
  await holen();
  toast(aktion === "leeren" ? "Chat geleert." : "Alles zurückgesetzt – bereit für eine neue Demo.");
});

// Start
passeFeldAn();
holen().then(nachUnten);
