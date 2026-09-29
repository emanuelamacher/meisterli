// Meisterli-Pilot: Aufnahme, Hochladen und Vorschau. Kein Framework.
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function stoppuhr(element, text) {
  const start = Date.now();
  element.textContent = `${text} 0 s`;
  const id = setInterval(() => {
    element.textContent = `${text} ${Math.round((Date.now() - start) / 1000)} s`;
  }, 500);
  return () => clearInterval(id);
}

// ---------------------------------------------------------------------------
// Startseite: Aufnahme / Datei / Text → /api/verarbeiten
// ---------------------------------------------------------------------------

function initEingabe(form) {
  const knopf = $("#aufnahme");
  const status = $("#aufnahme-status");
  const player = $("#aufnahme-player");
  const datei = $("#datei");
  const text = $("#text");
  const fehler = $("#fehler");
  const transkriptFehler = $("#transkript-fehler");
  let recorder = null;
  let aufnahme = null; // {blob, name}
  let stopTimer = null;

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

  knopf.addEventListener("click", async () => {
    if (recorder && recorder.state === "recording") {
      recorder.stop();
      return;
    }
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      status.textContent = "Dieser Browser kann nicht aufnehmen – bitte Datei hochladen.";
      return;
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      status.textContent = "Kein Zugriff auf das Mikrofon: " + e.message;
      return;
    }
    const [typ, endung] = mimeTyp();
    const teile = [];
    recorder = new MediaRecorder(stream, typ ? { mimeType: typ } : undefined);
    recorder.ondataavailable = (e) => e.data.size && teile.push(e.data);
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      stopTimer && stopTimer();
      const blob = new Blob(teile, { type: recorder.mimeType || typ });
      aufnahme = { blob, name: "aufnahme" + endung };
      player.src = URL.createObjectURL(blob);
      player.hidden = false;
      knopf.textContent = "● Neu aufnehmen";
      knopf.classList.remove("laeuft");
      status.textContent = `Aufnahme bereit (${Math.round(blob.size / 1024)} KB).`;
      datei.value = "";
    };
    recorder.start();
    knopf.textContent = "■ Aufnahme beenden";
    knopf.classList.add("laeuft");
    stopTimer = stoppuhr(status, "Aufnahme läuft …");
  });

  datei.addEventListener("change", () => {
    if (datei.files.length) {
      aufnahme = null;
      player.hidden = true;
      status.textContent = "";
    }
  });

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    fehler.hidden = true;
    transkriptFehler.hidden = true;
    const daten = new FormData();
    if (text.value.trim()) {
      daten.append("text", text.value.trim());
    } else if (aufnahme) {
      daten.append("audio", aufnahme.blob, aufnahme.name);
    } else if (datei.files.length) {
      daten.append("audio", datei.files[0]);
    } else {
      fehler.textContent = "Bitte eine Sprachnachricht aufnehmen, eine Datei wählen oder Text eingeben.";
      fehler.hidden = false;
      return;
    }
    const absenden = $("#verarbeiten");
    absenden.disabled = true;
    const hinweis = daten.has("audio")
      ? "Transkribiere und lese aus … (beim ersten Mal wird das Modell geladen)"
      : "Lese aus …";
    const stop = stoppuhr($("#fortschritt"), hinweis);
    try {
      const antwort = await fetch("/api/verarbeiten", { method: "POST", body: daten });
      const json = await antwort.json();
      if (!antwort.ok) {
        fehler.textContent = json.fehler || "Unbekannter Fehler.";
        fehler.hidden = false;
        if (json.transkript) {
          transkriptFehler.textContent = "Transkript: " + json.transkript;
          transkriptFehler.hidden = false;
        }
        return;
      }
      window.location.href = json.url;
    } catch (e) {
      fehler.textContent = "Server nicht erreichbar: " + e.message;
      fehler.hidden = false;
    } finally {
      stop();
      $("#fortschritt").textContent = "";
      absenden.disabled = false;
    }
  });
}

// ---------------------------------------------------------------------------
// Vorschau: Felder bearbeiten, Server rechnet, Rechnung erstellen
// ---------------------------------------------------------------------------

function initVorschau(form) {
  const tbody = $("#positionen");
  const fehlerListe = $("#fehler");
  let timer = null;

  function positionen() {
    return $$("tr.position", tbody).map((tr) => {
      const p = {};
      $$("input[data-f]", tr).forEach((i) => (p[i.dataset.f] = i.value));
      return p;
    });
  }

  function sammle() {
    const kunde = {};
    ["name", "strasse", "plz", "ort"].forEach((f) => (kunde[f] = form.elements["kunde." + f].value));
    return {
      entwurf_id: Number(form.dataset.entwurf),
      kunde,
      leistungsdatum: form.elements.leistungsdatum.value,
      zahlungsfrist_tage: form.elements.zahlungsfrist_tage.value,
      positionen: positionen(),
    };
  }

  function markiereFehler(fehler) {
    $$("input", form).forEach((i) => i.classList.remove("ungueltig"));
    Object.keys(fehler || {}).forEach((feld) => {
      const m = feld.match(/^positionen\.(\d+)\.(\w+)$/);
      let input = null;
      if (m) {
        const tr = $$("tr.position", tbody)[Number(m[1])];
        input = tr && $(`input[data-f="${m[2]}"]`, tr);
      } else {
        input = form.elements[feld];
      }
      input && input.classList && input.classList.add("ungueltig");
    });
  }

  async function neuBerechnen() {
    const antwort = await fetch("/api/berechnen", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ positionen: positionen() }),
    });
    if (!antwort.ok) return;
    const s = await antwort.json();
    $$("tr.position", tbody).forEach((tr, i) => ($(".betrag", tr).textContent = s.zeilen[i] || ""));
    $("#netto").textContent = s.netto;
    $("#mwst").textContent = s.mwst;
    $("#total").textContent = s.total;
    markiereFehler(s.fehler);
  }

  function spaeterBerechnen() {
    clearTimeout(timer);
    timer = setTimeout(neuBerechnen, 250);
  }

  form.addEventListener("input", (ev) => {
    ev.target.classList.remove("unsicher");
    if (ev.target.closest("#positionen")) spaeterBerechnen();
  });

  tbody.addEventListener("click", (ev) => {
    if (!ev.target.classList.contains("loeschen")) return;
    const zeilen = $$("tr.position", tbody);
    if (zeilen.length === 1) {
      $$("input", zeilen[0]).forEach((i) => (i.value = ""));
    } else {
      ev.target.closest("tr").remove();
    }
    neuBerechnen();
  });

  $("#position-neu").addEventListener("click", () => {
    const vorlage = $("tr.position", tbody);
    const neu = vorlage.cloneNode(true);
    $$("input", neu).forEach((i) => {
      i.value = "";
      i.classList.remove("unsicher", "ungueltig");
    });
    $(".betrag", neu).textContent = "";
    tbody.appendChild(neu);
    $("input", neu).focus();
  });

  // Bekannte Kunden: Adresse ausfüllen, wenn die Felder leer sind.
  const name = form.elements["kunde.name"];
  name.addEventListener("change", async () => {
    const antwort = await fetch("/api/kunden?name=" + encodeURIComponent(name.value));
    const k = await antwort.json();
    const hinweis = $("#kunde-hinweis");
    hinweis.textContent = "";
    if (!k.gefunden) return;
    let ergaenzt = false;
    ["strasse", "plz", "ort"].forEach((f) => {
      const input = form.elements["kunde." + f];
      if (!input.value.trim()) {
        input.value = k[f];
        input.classList.remove("unsicher");
        ergaenzt = true;
      }
    });
    if (ergaenzt) hinweis.textContent = "Bekannter Kunde – Adresse übernommen.";
  });

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    fehlerListe.hidden = true;
    const knopf = $("#erstellen");
    knopf.disabled = true;
    const stop = stoppuhr($("#fortschritt"), "Erstelle PDF …");
    try {
      const antwort = await fetch("/api/rechnungen", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sammle()),
      });
      const json = await antwort.json();
      if (!antwort.ok) {
        const fehler = json.fehler || { allgemein: "Unbekannter Fehler." };
        fehlerListe.innerHTML = "";
        Object.values(fehler).forEach((text) => {
          const li = document.createElement("li");
          li.textContent = text;
          fehlerListe.appendChild(li);
        });
        fehlerListe.hidden = false;
        markiereFehler(fehler);
        return;
      }
      window.location.href = json.url;
    } catch (e) {
      fehlerListe.innerHTML = "";
      const li = document.createElement("li");
      li.textContent = "Server nicht erreichbar: " + e.message;
      fehlerListe.appendChild(li);
      fehlerListe.hidden = false;
    } finally {
      stop();
      $("#fortschritt").textContent = "";
      knopf.disabled = false;
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const eingabe = $("#eingabe");
  if (eingabe) initEingabe(eingabe);
  const vorschau = $("#vorschau");
  if (vorschau) initVorschau(vorschau);
});
