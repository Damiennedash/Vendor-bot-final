const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
  LevelFormat, PageNumber, NumberFormat
} = require("docx");
const fs = require("fs");

const GREEN  = "075E54";
const LGREEN = "E8F5E9";
const YELLOW = "FFF9C4";
const LBLUE  = "E3F2FD";
const RED    = "FFEBEE";

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };

const h = (text, level = HeadingLevel.HEADING_1, color = GREEN) =>
  new Paragraph({
    heading: level,
    spacing: { before: 300, after: 120 },
    children: [new TextRun({ text, bold: true, color, font: "Arial",
      size: level === HeadingLevel.HEADING_1 ? 28 : 24 })]
  });

const p = (text, opts = {}) =>
  new Paragraph({
    spacing: { before: 80, after: 80 },
    children: [new TextRun({ text, font: "Arial", size: 20, ...opts })]
  });

const bullet = (text, bold = false) =>
  new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { before: 60, after: 60 },
    children: [new TextRun({ text, font: "Arial", size: 20, bold })]
  });

const note = (text, fill = YELLOW) =>
  new Table({
    width: { size: 9000, type: WidthType.DXA },
    columnWidths: [9000],
    rows: [new TableRow({ children: [
      new TableCell({
        borders, width: { size: 9000, type: WidthType.DXA },
        shading: { fill, type: ShadingType.CLEAR },
        margins: { top: 120, bottom: 120, left: 180, right: 180 },
        children: [new Paragraph({ children: [new TextRun({ text, font: "Arial", size: 19, italics: true })] })]
      })
    ]})]
  });

const codeBlock = (lines) =>
  new Table({
    width: { size: 9000, type: WidthType.DXA },
    columnWidths: [9000],
    rows: [new TableRow({ children: [
      new TableCell({
        borders, width: { size: 9000, type: WidthType.DXA },
        shading: { fill: "1E1E1E", type: ShadingType.CLEAR },
        margins: { top: 160, bottom: 160, left: 200, right: 200 },
        children: lines.map(line =>
          new Paragraph({ children: [new TextRun({ text: line, font: "Courier New", size: 18, color: "A8FF78" })] })
        )
      })
    ]})]
  });

const step = (n, title, fill = LGREEN) =>
  new Table({
    width: { size: 9000, type: WidthType.DXA },
    columnWidths: [700, 8300],
    rows: [new TableRow({ children: [
      new TableCell({
        borders, width: { size: 700, type: WidthType.DXA },
        shading: { fill: GREEN, type: ShadingType.CLEAR },
        margins: { top: 120, bottom: 120, left: 100, right: 100 },
        children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [
          new TextRun({ text: n, font: "Arial", size: 24, bold: true, color: "FFFFFF" })
        ]})]
      }),
      new TableCell({
        borders, width: { size: 8300, type: WidthType.DXA },
        shading: { fill, type: ShadingType.CLEAR },
        margins: { top: 120, bottom: 120, left: 180, right: 180 },
        children: [new Paragraph({ children: [new TextRun({ text: title, font: "Arial", size: 22, bold: true, color: GREEN })] })]
      })
    ]})]
  });

const envTable = (rows) =>
  new Table({
    width: { size: 9000, type: WidthType.DXA },
    columnWidths: [2800, 3200, 3000],
    rows: [
      new TableRow({ children: ["Variable", "Exemple", "Description"].map((h, i) =>
        new TableCell({
          borders, width: { size: [2800,3200,3000][i], type: WidthType.DXA },
          shading: { fill: GREEN, type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ children: [new TextRun({ text: h, font: "Arial", size: 19, bold: true, color: "FFFFFF" })] })]
        })
      )}),
      ...rows.map(([v, ex, desc]) =>
        new TableRow({ children: [v, ex, desc].map((val, i) =>
          new TableCell({
            borders, width: { size: [2800,3200,3000][i], type: WidthType.DXA },
            shading: { fill: "F9F9F9", type: ShadingType.CLEAR },
            margins: { top: 80, bottom: 80, left: 120, right: 120 },
            children: [new Paragraph({ children: [new TextRun({ text: val, font: i===1?"Courier New":"Arial", size: 18 })] })]
          })
        )})
      )
    ]
  });

const sp = () => new Paragraph({ spacing: { before: 0, after: 160 }, children: [] });

const doc = new Document({
  numbering: {
    config: [{
      reference: "bullets",
      levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } } }]
    }]
  },
  styles: {
    default: { document: { run: { font: "Arial", size: 20 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: GREEN },
        paragraph: { spacing: { before: 300, after: 120 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: "333333" },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 1 } },
    ]
  },
  sections: [{
    properties: {
      page: { size: { width: 11906, height: 16838 }, margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 } }
    },
    children: [
      // ── TITRE ───────────────────────────────────────────────────────────────
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 400, after: 200 },
        children: [new TextRun({ text: "🚀 Vendor WhatsApp + QR Pilot", font: "Arial", size: 44, bold: true, color: GREEN })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 0, after: 120 },
        children: [new TextRun({ text: "Guide Complet de Déploiement — Flask + Render + Google Sheets", font: "Arial", size: 22, color: "555555" })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 0, after: 400 },
        children: [new TextRun({ text: "Stack : Python Flask  •  WhatsApp Cloud API  •  Render.com  •  Google Sheets API", font: "Arial", size: 19, italics: true, color: "777777" })]
      }),

      // ── ARCHITECTURE ────────────────────────────────────────────────────────
      h("Vue d'ensemble de l'architecture"),
      note("QR Code → WhatsApp → Webhook (Flask sur Render) → Google Sheets en temps réel", LGREEN),
      sp(),
      p("Flux complet :"),
      bullet("Le vendor scanne le QR code avec son téléphone"),
      bullet("WhatsApp s'ouvre avec un message pré-rempli"),
      bullet("Le chatbot (géré par votre webhook Flask) guide le vendor en français"),
      bullet("Les réponses sont mappées sur les piliers PRIME"),
      bullet("Chaque réponse complète est écrite dans Google Sheets en temps réel"),
      sp(),

      // ── ÉTAPE 1 : META ───────────────────────────────────────────────────────
      h("ÉTAPE 1 — Configurer WhatsApp Cloud API (Meta)"),
      step("1", "Créer l'application Meta for Developers"),
      sp(),
      bullet("Aller sur https://developers.facebook.com"),
      bullet("Créer une application de type Business"),
      bullet("Ajouter le produit « WhatsApp »"),
      bullet("Dans Paramètres > WhatsApp > Configuration, noter le Phone Number ID"),
      sp(),
      step("2", "Lier votre numéro WhatsApp Business"),
      sp(),
      bullet("Aller dans WhatsApp > Numéros de téléphone"),
      bullet("Ajouter et vérifier votre numéro WhatsApp Business actif"),
      bullet("Générer un Access Token permanent (System User dans Business Manager)"),
      sp(),
      note("⚠️ L'Access Token temporaire expire après 24h. Utilise un System User Token permanent pour la production.", YELLOW),
      sp(),

      // ── ÉTAPE 2 : GOOGLE SHEETS ──────────────────────────────────────────────
      h("ÉTAPE 2 — Configurer Google Sheets API"),
      step("1", "Créer le Service Account Google"),
      sp(),
      bullet("Aller sur https://console.cloud.google.com"),
      bullet("Créer un projet (ex: vendor-checkin)"),
      bullet("Activer l'API : APIs > Bibliothèque > Google Sheets API > Activer"),
      bullet("IAM > Comptes de service > Créer un compte de service"),
      bullet("Créer une clé JSON et télécharger le fichier"),
      sp(),
      step("2", "Préparer Google Sheets"),
      sp(),
      bullet("Créer une Google Sheet avec un onglet nommé exactement « Réponses Vendors »"),
      bullet("Copier l'ID depuis l'URL : docs.google.com/spreadsheets/d/[ID ICI]/edit"),
      bullet("Partager la feuille avec l'email du Service Account (lecteur/éditeur)"),
      sp(),
      note("L'email du Service Account ressemble à : vendor-bot@projet.iam.gserviceaccount.com", LBLUE),
      sp(),

      // ── ÉTAPE 3 : RENDER ─────────────────────────────────────────────────────
      h("ÉTAPE 3 — Déployer sur Render.com"),
      step("1", "Préparer le dépôt GitHub"),
      sp(),
      bullet("Créer un dépôt GitHub et pousser le code du projet"),
      bullet("Structure attendue :"),
      sp(),
      codeBlock([
        "vendor_bot/",
        "├── app/",
        "│   ├── __init__.py",
        "│   ├── main.py          ← point d'entrée Flask",
        "│   ├── conversation.py  ← machine à états du chatbot",
        "│   ├── whatsapp.py      ← envoi de messages",
        "│   └── sheets.py        ← écriture Google Sheets",
        "├── qr/",
        "│   └── generate_qr.py   ← génération du QR code",
        "├── Procfile",
        "├── requirements.txt",
        "└── .env.example",
      ]),
      sp(),
      step("2", "Créer le Web Service sur Render"),
      sp(),
      bullet("Aller sur https://render.com > New > Web Service"),
      bullet("Connecter votre dépôt GitHub"),
      bullet("Paramètres :"),
      codeBlock([
        "Build Command : pip install -r requirements.txt",
        "Start Command : gunicorn 'app.main:app' --bind 0.0.0.0:$PORT --workers 2",
        "Environment   : Python 3.11",
        "Plan          : Free (suffisant pour le pilote)",
      ]),
      sp(),
      step("3", "Ajouter les variables d'environnement"),
      sp(),
      envTable([
        ["WHATSAPP_TOKEN",        "EAAxxxxxx",                   "Access Token Meta"],
        ["WHATSAPP_PHONE_ID",     "123456789",                   "Phone Number ID"],
        ["WHATSAPP_VERIFY_TOKEN", "montoken2024",                "Token de vérification webhook (libre)"],
        ["GOOGLE_SHEET_ID",       "1BxiMVs0XRA...",             "ID de votre Google Sheet"],
        ["GOOGLE_SHEET_TAB",      "Réponses Vendors",           "Nom de l'onglet"],
        ["GOOGLE_CREDENTIALS_JSON","{ \"type\":\"service_account\"...}", "JSON complet sur 1 ligne"],
      ]),
      sp(),
      note("Pour GOOGLE_CREDENTIALS_JSON : ouvrir le fichier JSON téléchargé, copier TOUT le contenu, le coller en une seule ligne dans la variable.", YELLOW),
      sp(),

      // ── ÉTAPE 4 : WEBHOOK META ───────────────────────────────────────────────
      h("ÉTAPE 4 — Enregistrer le webhook dans Meta"),
      p("Une fois Render déployé, vous avez une URL publique du type :"),
      codeBlock(["https://vendor-bot-xxxx.onrender.com"]),
      sp(),
      p("Dans Meta for Developers > WhatsApp > Configuration du webhook :"),
      bullet("URL de rappel : https://vendor-bot-xxxx.onrender.com/webhook"),
      bullet("Token de vérification : (votre WHATSAPP_VERIFY_TOKEN)"),
      bullet("Cliquer Vérifier et enregistrer"),
      bullet("Abonnements : cocher messages"),
      sp(),
      note("✅ Si la vérification réussit, Meta envoie un GET avec hub.challenge et le webhook répond 200.", LGREEN),
      sp(),

      // ── ÉTAPE 5 : QR CODE ────────────────────────────────────────────────────
      h("ÉTAPE 5 — Générer le QR Code final"),
      p("Depuis votre machine locale (Python installé) :"),
      codeBlock([
        "cd vendor_bot/qr",
        "python generate_qr.py --phone 22890123456 --output qr_vendor_final.png",
      ]),
      sp(),
      bullet("Remplacer 22890123456 par votre vrai numéro WhatsApp Business (avec indicatif pays, sans +)"),
      bullet("Le QR code pointe vers : wa.me/22890123456?text=Bonjour..."),
      bullet("Imprimer en couleur, plastifier, afficher chez chaque micro-distributeur"),
      sp(),
      note("Taille recommandée pour impression : 10cm × 10cm minimum pour une lecture facile.", LBLUE),
      sp(),

      // ── TEST ─────────────────────────────────────────────────────────────────
      h("ÉTAPE 6 — Tester le système complet"),
      step("✓", "Checklist de validation avant lancement", LGREEN),
      sp(),
      bullet("Webhook vérifié dans Meta for Developers (status ✅)"),
      bullet("Render affiche « Live » dans le dashboard"),
      bullet("Envoyer un message WhatsApp test au numéro → le bot répond"),
      bullet("Compléter un flow entier → vérifier la ligne dans Google Sheets"),
      bullet("QR code scanné avec 3 téléphones différents → fonctionne"),
      bullet("Tester le mot-clé MENU → affiche le menu"),
      sp(),

      // ── PILIER PRIME ─────────────────────────────────────────────────────────
      h("Référentiel PRIME — Mapping des réponses"),
      new Table({
        width: { size: 9000, type: WidthType.DXA },
        columnWidths: [1600, 3000, 2200, 2200],
        rows: [
          new TableRow({ children: ["Pilier", "Signification vendor", "Choix WhatsApp", "Colonne Sheets"].map((h, i) =>
            new TableCell({
              borders, width: { size: [1600,3000,2200,2200][i], type: WidthType.DXA },
              shading: { fill: GREEN, type: ShadingType.CLEAR },
              margins: { top: 80, bottom: 80, left: 120, right: 120 },
              children: [new Paragraph({ children: [new TextRun({ text: h, font: "Arial", size: 18, bold: true, color: "FFFFFF" })] })]
            })
          )}),
          ...[
            ["Product",      "Produit, qualité, fraîcheur",  "1 — Problème Produit",       "Product"],
            ["Relationship", "Relation micro-distributeur",  "2 — Problème Relation",      "Relationship"],
            ["Income",       "Commission, paiement, bonus",  "3 — Revenu / paiement",      "Income"],
            ["Motivation",   "Formation, conseils de vente", "4 — Motivation / formation", "Motivation"],
            ["Equipment",    "Glacière, vélo, uniforme",     "5 — Problème Équipement",    "Equipment"],
          ].map(([p1, p2, p3, p4]) =>
            new TableRow({ children: [p1, p2, p3, p4].map((val, i) =>
              new TableCell({
                borders, width: { size: [1600,3000,2200,2200][i], type: WidthType.DXA },
                shading: { fill: "F5F5F5", type: ShadingType.CLEAR },
                margins: { top: 80, bottom: 80, left: 120, right: 120 },
                children: [new Paragraph({ children: [new TextRun({ text: val, font: "Arial", size: 18, bold: i === 3 })] })]
              })
            )})
          )
        ]
      }),
      sp(),

      // ── FIN ──────────────────────────────────────────────────────────────────
      note("📩 Questions ? Contactez l'équipe data pour l'accès Google Sheets et la configuration Meta Business.", LGREEN),
    ]
  }]
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync("/mnt/user-data/outputs/vendor_deployment_guide.docx", buf);
  console.log("Guide Word créé ✅");
});
