# -*- coding: utf-8 -*-

"""

Generateur QR Code unique - FANMILK TOGO Vendor Support

Lancez ce script pour generer le QR code :

    python generer_qr_fanmilk.py

"""

import qrcode

from qrcode.image.styledpil import StyledPilImage

from qrcode.image.styles.moduledrawers import RoundedModuleDrawer

from PIL import Image, ImageDraw, ImageFont

# ══════════════════════════════════════════════════════

# CONFIGURATION — modifiez uniquement cette section

# ══════════════════════════════════════════════════════

WA_PHONE    = "22899432898"       # Votre numero WhatsApp Business (sans +)

BRAND       = "FANMILK TOGO"      # Nom de la marque

OUTPUT_FILE = "fanmilk_qr.png"   # Nom du fichier de sortie

# ══════════════════════════════════════════════════════


def generer_qr():

    # Message qui s'ouvre automatiquement dans WhatsApp

    msg = "Bonjour {}".format(BRAND)

    url = "https://wa.me/{}?text={}".format(

        WA_PHONE,

        msg.replace(" ", "%20")

    )

    print("URL generee : {}".format(url))

    # Creer le QR code

    qr = qrcode.QRCode(

        version=3,

        error_correction=qrcode.constants.ERROR_CORRECT_H,

        box_size=14,

        border=3,

    )

    qr.add_data(url)

    qr.make(fit=True)

    img = qr.make_image(

        image_factory=StyledPilImage,

        module_drawer=RoundedModuleDrawer()

    ).convert("RGBA")

    W, H = img.size

    # Ajouter le bandeau vert en bas

    canvas = Image.new("RGBA", (W, H + 110), (255, 255, 255, 255))

    canvas.paste(img, (0, 0))

    draw = ImageDraw.Draw(canvas)

    # Bandeau vert FANMILK

    draw.rectangle([0, H, W, H + 110], fill=(0, 102, 51, 255))

    # Textes

    try:

        font_bold  = ImageFont.truetype(

            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)

        font_small = ImageFont.truetype(

            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)

    except:

        font_bold  = ImageFont.load_default()

        font_small = font_bold

    draw.text((W//2, H + 28),

              "{} — Vendor Support".format(BRAND),

              fill="white", font=font_bold, anchor="mm")

    draw.text((W//2, H + 58),

              "Scannez pour votre declaration quotidienne",

              fill=(200, 255, 200), font=font_small, anchor="mm")

    draw.text((W//2, H + 82),

              "WhatsApp Check-In  |  wa.me/{}".format(WA_PHONE),

              fill=(180, 240, 180), font=font_small, anchor="mm")

    canvas.save(OUTPUT_FILE)

    print("QR code sauvegarde : {}".format(OUTPUT_FILE))

    print("Imprimez-le en couleur (min 10cm x 10cm) et plastifiez-le !")


if __name__ == "__main__":

    generer_qr()
 