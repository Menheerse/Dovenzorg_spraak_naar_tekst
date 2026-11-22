# Meelezen

Kerkgangers lezen de preek live mee op hun telefoon, met vertaling voor anderstaligen. Het geluid komt van de live-uitzending op kerkdienstgemist.nl. Per dienst worden de opname en de uitgeschreven tekst op de NAS bewaard.

```
kerkdienstgemist.nl ──► laptop met videokaart ──► telefoons in de kerk
  (live mp3)            ffmpeg → Whisper           (via internet, https)
                        → vertaling
                        → NAS: opname.mp3, tekst.txt, ondertitels.srt
```

## 1. Installeren (Windows-laptop)

### Op een nieuwe computer (alles in één keer)

1. **Oude computer** (alleen als u instellingen en gegevens wilt meenemen): kopieer `OVERZETTEN-VAN-OUDE-COMPUTER.bat` naar de map van Meelezen, bijvoorbeeld `C:\meelezen`, en dubbelklik erop. Op het bureaublad komt `meelezen-overzetten.zip`. Daarin zitten config.toml (met de stream-adressen en sleutels), de Bijbel, het psalmboek, de diensten en eventueel de opnames.
2. Zet de zip van de installatie, en zo nodig `meelezen-overzetten.zip`, op de **nieuwe computer**. Zet ze bijvoorbeeld op het bureaublad of in Downloads.
3. Pak de installatie-zip uit en dubbelklik op **INSTALLEREN-NIEUWE-COMPUTER.bat**. Waarschuwt Windows ("Windows heeft uw pc beschermd"), kies dan *Meer informatie → Toch uitvoeren*.
4. De installatie doet daarna alles zelf:
   - kopieert de app naar `C:\meelezen` (of een andere map naar keuze);
   - zet de gegevens van de oude computer terug;
   - installeert Python, ffmpeg en de onderdelen;
   - haalt de Bijbel, het psalmboek en het spraakmodel op;
   - maakt een snelkoppeling **Meelezen** op het bureaublad.
   - Daarna vraagt hij of Meelezen automatisch moet starten, of de slaapstand uit moet, of telefoons in het netwerk erbij mogen (firewall) en of Tailscale moet worden ingesteld.
5. **Tailscale:** verwijder eerst de oude computer op https://login.tailscale.com/admin/machines, of zet Tailscale daar uit. Zo krijgt de nieuwe computer weer de naam `meelezen` en blijft het internetadres (`https://meelezen.<uw-tailnet>.ts.net`) gelijk. Anders werken de QR-codes niet meer.

De uitleg hieronder is voor wie het stap voor stap met de hand doet.

1. Python hoeft u niet zelf te installeren: installeren.bat zet zo nodig **Python 3.12** naast een eventuele andere versie. De nieuwste versies (3.14 en 3.15) werken nog niet met de spraakherkenning.
2. Zorg dat het stuurprogramma van de NVIDIA-videokaart actueel is (via de NVIDIA App).
3. Pak deze map uit, bijvoorbeeld naar `C:\Meelezen`.
4. Dubbelklik op **installeren.bat**. Dit installeert alles, ook ffmpeg, en duurt een paar minuten.
5. Dubbelklik op **demo.bat** en open op de laptop `http://localhost:8080`. U ziet een voorbeeldpreek voorbijkomen. Werkt dat, dan is de app goed geïnstalleerd.

### Welke laptop?

De app kiest zelf (`engine = "auto"`):

| Laptop | Spraakherkenning | Kwaliteit | Kosten |
|---|---|---|---|
| Met NVIDIA-videokaart (bijv. RTX PRO 2000 Blackwell) | op de computer, model large-v3 | uitstekend | gratis |
| Oudere laptop zonder videokaart, met OpenAI-sleutel | via OpenAI | uitstekend | ± € 0,35 per uur |
| Oudere laptop zonder videokaart en zonder sleutel | op de processor, model small | redelijk, kan achterlopen | gratis |

Na de installatie draait **controle.bat** automatisch: die meet hoe snel de laptop is en geeft advies. Op een oudere laptop, zoals een Dell Latitude, is OpenAI meestal de beste keuze. De laptop doet dan alleen het lichte werk: het geluid ophalen, de telefoons bedienen en opslaan op de NAS.

### NVIDIA RTX PRO 2000 Blackwell (en andere Blackwell-kaarten)

De app is hierop afgestemd:
- **Stuurprogramma eerst.** Installeer vóór de installatie het nieuwste stuurprogramma via de NVIDIA App. Blackwell heeft versie 572 of hoger nodig. controle.bat waarschuwt als het te oud is.
- **CUDA 12.8 of nieuwer.** Blackwell werkt pas vanaf CUDA 12.8. `requirements-nvidia.txt` installeert daarom cuBLAS 12.8 of nieuwer en CTranslate2 4.6 of nieuwer.
- **Rekentype float16.** Op Blackwell geeft het rekentype int8 de fout `CUBLAS_STATUS_NOT_SUPPORTED`. De app kiest daarom zelf float16. Lukt dat niet, dan probeert hij bfloat16 en daarna float32. Bij het starten test hij elk rekentype met een proefrun.
- **Model.** De app meet bij het starten hoe snel het model is. De eerste meting telt niet: dan is de kaart nog aan het opwarmen. Op een kaart met 8 GB (de laptopversie) die ook de vertaling met Ollama doet, kiest hij large-v3-turbo. Dat model is half zo groot, zodat Whisper en het vertaalmodel (gemma3:4b) samen in het geheugen passen. Op een kaart met 12 GB of meer kiest hij het beste model, large-v3. Is het te traag voor twee kerken tegelijk, dan schakelt hij vanzelf over op large-v3-turbo.
- **Twee kerken tegelijk.** De kaart verwerkt een stuk preek in een fractie van een seconde. De twee kerken kunnen het model dus om de beurt gebruiken, zonder dat de tekst achterloopt. Zo blijft er geheugen over voor de vertaling.
- **Gratis vertalen met Ollama (automatisch).** Heeft de computer een NVIDIA-kaart, dan installeert installeren.bat zelf Ollama met een vertaalmodel. Op een kaart met 16 GB is dat gemma3:12b (± 9 GB), naast Whisper (± 4 GB). Op een kaart met 8 GB is het gemma3:4b. In config.toml wordt de vertaling daarop gezet, behalve als u al een OpenAI- of DeepL-sleutel hebt. Bij het starten zet de app Ollama zelf aan en laadt hij het model alvast op de videokaart, zodat de eerste zin meteen vertaald wordt. Engels en de andere talen kosten dan niets en gaan niet over internet. Opnieuw instellen kan met `.venv\Scripts\python -m meelezen.ollama installeren`.

### Bijwerken naar een nieuwe versie

Pak de nieuwe zip uit over de oude map. Je eigen bestanden blijven daarbij staan: `config.toml`, `data\bijbel.json`, `data\psalmen.json` en de `dienst-…json`-bestanden zitten niet in de zip. Bij de eerste start maakt de app `config.toml` aan op basis van `config.voorbeeld.toml`.

## 2. Instellen: config.toml

Open `config.toml` met Kladblok. De belangrijkste instellingen:

| Instelling | Wat |
|---|---|
| `kerknaam` | De naam bovenaan in de app |
| `stream_url` | Het adres van de live-uitzending (staat al goed) |
| `[opslag] map` | De map op de NAS, bijvoorbeeld `'\\NAS\kerk\diensten'` |
| `[spraak] model` | `large-v3` (beste) of `large-v3-turbo` (sneller) |
| `[vertaling] engine` | `openai`, `deepl` of `uit` |
| `[sleutels]` | Uw OpenAI- of DeepL-sleutel |

Daarna start u de app met **start.bat**. Bij de eerste start wordt het spraakmodel gedownload (ongeveer 3 GB).

start.bat vraagt eerst wat u wilt doen:

1. **Livestream volgen**, zoals ingesteld in config.toml.
2. **Een mp3-bestand afspelen.** Er opent een Verkenner-venster om de opname te kiezen. Daarna vraagt de app bij welke kerk de opname hoort, en vanaf welk tijdstip hij moet afspelen. De opname wordt in normaal tempo afgespeeld, alsof het live is. De tekst wordt opgeslagen; het geluid niet nog een keer.
3. **Demo**, een voorbeeldpreek zonder geluid.

**start-live.bat** start direct de livestream, zonder vragen.

### Testen zonder dat er een dienst is

Download een opname van een eerdere dienst als mp3 en start:

```
start.bat --bestand C:\pad\naar\dienst.mp3
```

Het bestand wordt in normaal tempo afgespeeld, alsof het live is. Zo ziet u hoe goed de herkenning en de vertaling werken.

### Twee kerken (of meer)

Bovenaan in config.toml staan de kerken, elk in een eigen blok `[[kerk]]`:

```
[[kerk]]
id = "gergem"
naam = "Ger. Gem. Middelharnis"
plaats = "Middelharnis"
stream_url = "https://….kerkdienstgemist.nl/…?type=live.mp3"

[[kerk]]
id = "hhg"
naam = "HHG Middelharnis-Sommelsdijk"
plaats = "Middelharnis-Sommelsdijk"
stream_url = "https://www.youtube.com/@…/live"
```

- **Kiezen:** wie de app opent, kiest eerst een kerk. Bij elke kerk staat of die nu live is. De keuze wordt onthouden, en via het menu (*Andere kerk kiezen*) kan men wisselen.
- **QR-code per kerk:** maak een QR-code van `https://meelezen.<uw-tailnet>.ts.net/?kerk=gergem` en een van `…/?kerk=hhg`. Wie scant, komt dan direct bij de juiste kerk, zonder keuzescherm.
- **Opslag:** elke kerk krijgt op de NAS een eigen map, bijvoorbeeld `diensten\Ger. Gem. Middelharnis\2026-11-22_0930_ochtend`.
- **Bijbel bij de dienst per kerk:** gebruik `data\dienst-gergem.json` en `data\dienst-hhg.json`. Bestaat zo'n bestand niet, dan geldt `data\dienst.json`.
- **Rekenkracht:** vallen de diensten van beide kerken tegelijk, dan moet de laptop twee preken tegelijk omzetten. Op de processor van een oudere laptop lukt dat niet bij. Gebruik dan OpenAI; dat kan beide tegelijk.
- Een kerk zonder `stream_url` staat op het keuzescherm als *Nog niet beschikbaar*.

### YouTube in plaats van kerkdienstgemist

Zendt de kerk live uit op YouTube? Zet dan in config.toml:

```
stream_url = "https://www.youtube.com/@KanaalNaam/live"
```

- De app controleert elke halve minuut of het kanaal live is, en begint dan vanzelf.
- De opname op de NAS wordt een gewone mp3.
- YouTube loopt zelf al 10 tot 30 seconden achter op de werkelijkheid, dus de tekst komt iets later dan bij kerkdienstgemist.
- YouTube verandert regelmatig. Daarom werkt start.bat bij elke start het hulpprogramma yt-dlp bij. Werkt YouTube ineens niet meer, voer dan installeren.bat opnieuw uit.
- Gebruik dit alleen voor het eigen kanaal van de kerk, of met toestemming van de eigenaar.

### Melding 'geen uitzending'

Na de dienst laat kerkdienstgemist steeds de melding horen: "Geachte luisteraar, er is op dit moment geen uitzending". De app herkent die melding. Hij zet haar niet in de tekst en telt haar niet als geluid. De dienst wordt zo gewoon 5 minuten na het laatste echte geluid afgesloten, en de opname wordt daar afgeknipt. Hoort de app vóór de dienst alleen deze melding, dan bewaart hij niets.

Opnames van vóór deze versie bevatten soms tientallen korte bestanden `opname_deel2.mp3`, `opname_deel3.mp3` enzovoort, met alleen die melding. Ruim ze op met **opruimen.bat**. Dat haalt ook de melding uit tekst.txt, de ondertitels en dienst.json. Het laat eerst zien wat er weg kan en vraagt om bevestiging.

### Formulieren

Op de Bijbel-pagina staat het tabblad **Formulieren**. Daar staan de klassieke formulieren in de Statenvertaling-versie:
- Heilig Avondmaal;
- Doop (kinderen);
- Doop (volwassenen);
- Openbare geloofsbelijdenis;
- Bevestiging dienaren des Woords;
- Bevestiging ouderlingen en diakenen;
- Huwelijk;
- Christelijke ban;
- Wederopneming.

start.bat haalt ze de eerste keer zelf op van ipsalm.nl. Opnieuw ophalen kan met `formulieren-ophalen.bat`.

### Voorgelezen tekst rechtzetten

Whisper verstaat voorgelezen teksten niet altijd goed. Voorbeelden zijn 'gedachten is' (gedachtenis), 'nog' (noch) en 'niet ons schuldig' (onschuldig). Daarom zoekt de app bij elke zin of die uit een bekende tekst wordt voorgelezen. Is dat zo, dan zet hij de officiële tekst neer. Hij kijkt in:
- de Statenvertaling;
- de berijmde psalmen;
- de formulieren;
- het Onze Vader, de Twaalf Artikelen en het votum;
- uw eigen teksten in `data\vaste-teksten\*.txt`, één tekst per bestand. Bijvoorbeeld een gebed of formulier in de woorden van uw eigen kerk.

De app vervangt alleen als het stuk voor minstens 82% overeenkomt. Eigen woorden van de predikant ervoor of erna blijven staan. Uitzetten kan met `vaste_teksten = false` onder `[spraak]`.

Verder:
- **Woordenlijst-echo:** bij stilte of orgelspel zegt Whisper soms de woordenlijst op ("Heere, Jezus Christus, Heilige Geest, Heilige Geest…"). Zulke regels worden nu weggefilterd.
- **Uitgebreide woordenlijst:** de standaardwoordenlijst bevat nu ook woorden die vaak fout gingen, zoals gedachtenis, belijden, goedertierenheid, ijdellijk, toorn en heirscharen. Hebt u de oude standaardlijst nog in config.toml, dan gebruikt de app vanzelf de nieuwe. Een eigen lijst blijft staan.
- **Bijbelverwijzingen:** een kort citaat wordt alleen nog gekoppeld als het past bij het hoofdstuk dat net gelezen of genoemd is. Zo komen er geen verkeerde links meer zoals Spreuken 23:34 bij Psalm 46.

### Welke livestream?

Kiest u in start.bat voor **1. Livestream volgen**, dan vraagt de app welke kerk u wilt volgen:

1. Ger. Gem. Middelharnis
2. HHG Middelharnis-Sommelsdijk
3. Beide

Met één kerk heeft de computer minder werk. Opent iemand de QR-code van de andere kerk, dan ziet hij dat die livestream nu niet wordt gevolgd.

Zonder vragen starten kan ook, bijvoorbeeld in een snelkoppeling: `start-live.bat --kerk gergem`, `start-live.bat --kerk hhg` of `start-live.bat --kerk beide`. Alleen `start-live.bat` volgt beide.

### Kerk wisselen

Tik bovenaan op de **naam van de kerk** (met het pijltje ˅). Er verschijnt een lijstje met beide kerken, en bij elke kerk staat of die nu live is. Tik op een kerk en u wisselt meteen. Een kerk waarvan de livestream nu niet wordt gevolgd, staat er grijs bij.

### Taal kiezen

Tik rechtsboven op de **wereldbol**. Er verschijnt een lijstje met de talen. Tik op een taal en de tekst wisselt meteen. Bij een vertaling kunt u er ook de Nederlandse tekst bij laten zien. Het menu hoeft u er niet voor te openen.

### Terug naar de preek

Zit u in de Bijbel, het psalmboek of de verklaring van Matthew Henry? Tik dan bovenaan op **‹ Live**. Met één tik bent u terug bij de preek, bij de nieuwste tekst. Dat werkt ook vanuit het venster met een bijbeltekst.

### Luisteren: het geluid erbij

Bovenaan in de app staat de knop **🔊 Luister**. Daarmee hoort u de dienst terwijl u meeleest.
- **Gelijk met tekst** (standaard): het geluid loopt een paar seconden achter, ongeveer gelijk met de tekst. De tekst verschijnt pas als een zin is uitgesproken. In config.toml stelt u dit in met `[luisteren] vertraging`.
- **Direct (live):** zo snel mogelijk, zonder vertraging. Kies dit in het menu onder *Geluid*.
- Het geluid komt uit dezelfde verbinding als de spraakherkenning. Er komt geen extra verbinding met kerkdienstgemist of YouTube bij.
- Ook bij een mp3 die u afspeelt (start.bat, keuze 2) hoort u het geluid.
- Op de telefoon blijft het geluid doorspelen als het scherm uit gaat. Het is te bedienen vanaf het vergrendelscherm.
- **Internet:** elke luisteraar gebruikt ongeveer 60 MB per uur (128 kbps) van de upload van de computer thuis. Bij 20 luisteraars is dat 2,5 Mbit/s upload. Zet bij veel luisteraars `kbps = 96`.

### Orgelspel en samenzang

Speelt het orgel of zingt de gemeente, dan verschijnt in de app een melding **♪ Orgelspel** of **♪ Samenzang**, in de taal van de lezer. Bij een voorspel, het zingen en een naspel wisselt de melding mee: Orgelspel → Samenzang → Orgelspel. Er komt pas een nieuwe melding als de verandering minstens 30 seconden duurt, zodat een orgeltussenspel tussen twee verzen het zingen niet onderbreekt.

De herkenning is afgesteld op een echte opname van een hele dienst (Pinksteren 2026). Zang en orgel worden onderscheiden met drie kenmerken: zang klinkt 'breder', luider dan de spreker en hoger. De app meet tijdens de dienst zelf hoe luid er gesproken wordt, dus een andere geluidsinstelling van de stream maakt weinig uit. Heel zacht orgelspel (bijna stil) wordt niet gemeld. In tekst.txt en de ondertitels staat het ook, met de duur erbij.

Deze stukken gaan niet door de spraakherkenning. Dat voorkomt verzonnen tekst, en het spaart rekenwerk op een trage laptop of kosten bij OpenAI.

**Afstellen op uw kerk**

1. Sleep een opname van een dienst op **muziektest.bat**. Binnen een minuut ziet u een tijdlijn, bijvoorbeeld:
   ```
   00:00:00 – 00:04:10  ♪ orgelspel
   00:04:10 – 00:09:30  ♪ samenzang
   00:09:30 – 00:12:00  spraak
   ```
2. Klopt de tijdlijn niet met de opname? Pas dan in config.toml onder `[muziek]` de waarden aan. muziektest.bat zegt welke kant op.
3. Met `herkennen = false` zet u de herkenning helemaal uit.

### Bijbelteksten in de preek

Noemt de predikant een tekst, zoals "Johannes 10 vers 11", "Psalm drieëntwintig" of "de eerste brief aan de Korinthiërs, hoofdstuk 13", dan wordt die in de app onderstreept en klikbaar. Citeert hij een vers uit de Statenvertaling zonder het te noemen, dan herkent de app dat ook: de geciteerde woorden krijgen een stippellijn, met de bron erachter, bijvoorbeeld **Psalmen 23:4**.

- Een tik opent het vers in de Statenvertaling, met het hele hoofdstuk eromheen en knoppen naar het vorige en volgende hoofdstuk.
- Wie een vertaling leest, ziet de bronnen als knopjes achter de zin, zoals 📖 Psalmen 23:4.
- In tekst.txt op de NAS staat bij een citaat de bron erachter.
- Hiervoor is de complete bijbel nodig (bijbel-ophalen.bat).

### Preektekst downloaden

In het menu staan onder **Preektekst downloaden** twee knoppen: **PDF** en **Word**. Na afloop van de dienst staan ze ook onder de tekst.

- Je krijgt de hele tekst van de dienst tot dat moment, als doorlopend verhaal in alinea's. Erin staan ook de kerk, de datum, de voorganger (uit dienst.json), samenzang en orgelspel, en de bronnen van bijbelcitaten.
- De tekst komt in de taal die de lezer gekozen heeft. Zinnen die nog niet vertaald waren, worden eerst vertaald. Dat kan even duren.
- **PDF** opent op elke telefoon en is goed om te printen. **Word** is handig om de tekst te bewerken of te bewaren.
- Voor Arabisch, Farsi, Tigrinya, Amhaars en Chinees maakt de PDF-knop een Word-bestand, omdat de PDF-maker die schriften niet goed weergeeft.
- Het bestand is beschikbaar tot de volgende dienst begint. Oudere diensten staan als tekst op de NAS.

## 3. Opslaan op de NAS

Per dienst maakt de app een map aan, bijvoorbeeld `2026-11-15_0930_ochtend`, met daarin:

| Bestand | Inhoud |
|---|---|
| `opname.mp3` | Het geluid, ongewijzigd uit de uitzending. Valt de stream even weg, dan volgt `opname_deel2.mp3` |
| `tekst.txt` | De preek met tijden: `[00:12:34] …` |
| `ondertitels.srt` | Ondertitels die passen bij opname.mp3 (te openen in VLC) |
| `tekst_en.txt`, `ondertitels_en.srt`, … | Vertalingen, voor talen die iemand heeft gekozen |
| `dienst.json` | Alles samen, voor eventueel later gebruik |

- **Windows:** open de NAS-map eerst één keer in de Verkenner en vink *Mijn referenties onthouden* aan. Zet het pad in config.toml tussen **enkele** aanhalingstekens: `map = '\\NAS\kerk\diensten'`.
- **Linux:** koppel de NAS eerst, bijvoorbeeld via `/etc/fstab` als `/mnt/nas`.
- Tekst en opname worden los van elkaar opgeslagen. Is de NAS even onbereikbaar, dan gaat het meelezen gewoon door en wordt de tekst later alsnog weggeschreven. Op `http://localhost:8080/api/status` ziet u of opslaan lukt.
- **Afsluiten:** is er 5 minuten geen geluid meer, dan sluit de app de dienst af. De mp3 wordt dan netjes afgesloten, de stilte aan het eind eraf geknipt (op 30 seconden na), en de tekst definitief opgeslagen. Dit geldt ook als de uitzending gewoon doorloopt na de dienst. Komt er daarna weer geluid, dan begint vanzelf een nieuwe dienst met een nieuwe map. Instellen kan met `afsluiten_na_minuten` in config.toml.
- Met `bewaar_dagen` ruimt de app oude diensten automatisch op.

## 4. Bereikbaar maken voor de kerk

De laptop staat thuis, dus de telefoons in de kerk bereiken hem via internet. De eenvoudigste manier is **Tailscale Funnel**. Dat is gratis, u hoeft niets in te stellen op de router, en het adres is altijd hetzelfde en beveiligd (https).

1. Installeer Tailscale (tailscale.com/download) en log in.
2. Zet in de beheeromgeving van Tailscale *HTTPS* en *Funnel* aan.
3. Open een opdrachtprompt en typ: `tailscale funnel --bg 8080`
4. U krijgt een adres zoals `https://laptop.tail1234.ts.net`. Dat adres blijft hetzelfde.
5. Maak er een **QR-code** van en hang die op in de kerk of zet hem in de liturgie.

> **Let op:** de functie *Scherm aan laten* werkt alleen via een https-adres. Met Tailscale Funnel is dat automatisch geregeld.

Een alternatief is Cloudflare Tunnel met een eigen domeinnaam, bijvoorbeeld `meelezen.uwkerk.nl`.

**Laat de laptop tijdens de diensten aan staan.** Stel bij *Energiebeheer* ook in dat er niets gebeurt als u het deksel dichtklapt. Zet in Windows bij *Energiebeheer* de slaapstand uit wanneer de laptop op de netstroom staat. Laat de app automatisch starten met **start-live.bat**: zet daar een snelkoppeling van in `shell:startup`. Gebruik daarvoor niet start.bat, want die wacht op een keuze.

## 5. Bestaande opname omzetten naar tekst

Dubbelklik op **mp3-omzetten.bat**. Plak een YouTube-link, bijvoorbeeld van een eerdere dienst, of druk op Enter en kies een of meer opnames (mp3, wav, m4a en andere). Het geluid van een YouTube-link komt op de NAS in de map `youtube`. U kunt de bestanden ook op mp3-omzetten.bat slepen. Als vertaling is ingesteld, vraagt het programma of u ook vertalingen wilt, bijvoorbeeld `en,de`.

Naast elke opname komen deze bestanden:

| Bestand | Inhoud |
|---|---|
| `naam.txt` | De tekst met tijden |
| `naam.srt` | Ondertitels. VLC toont ze vanzelf bij de mp3 |
| `naam.en.txt`, `naam.en.srt` | De vertalingen |

- Het omzetten gaat sneller dan de opname lang is. Hoeveel sneller hangt af van de laptop en van de gekozen spraakherkenning.
- Het kan ook terwijl de live-app draait.
- Wilt u nauwkeuriger omzetten op de processor, en mag het langer duren? Gebruik dan een groter model. Typ in een opdrachtvenster in de map: `.venv\Scripts\python -m meelezen.omzetten --model medium`

## 6. Bijbel

Onder **Bijbel** in het menu staat de hele Statenvertaling. Je kunt erin bladeren (boek → hoofdstuk), vooruit en terug naar het volgende of vorige hoofdstuk, en zoeken. Typ een verwijzing, zoals `Joh 3:16` of `ps 23`, of een of meer woorden, zoals `goede herder`. De app onthoudt waar je was. Hiervoor is de complete bijbel nodig (bijbel-ophalen.bat).

### Bijbelverklaring (Matthew Henry)

Bij elk bijbelhoofdstuk staan twee knoppen: **Bijbeltekst** en **Verklaring (M. Henry)**. De verklaring is per gedeelte ingedeeld, bijvoorbeeld "Verzen 1–17". Bijbelverwijzingen in de verklaring zijn klikbaar. In de bijbeltekst is elk **versnummer** een link: tik erop en de uitleg van Matthew Henry bij precies dat vers gaat open. Tik je in de live-tekst op een bijbeltekst, dan staat onderaan het venster de knop **Verklaring**: die opent direct het juiste gedeelte.

De verklaring staat in `data\henry.db` (alle 66 boeken). Die zit niet in de gewone zip, maar wordt apart geleverd. Pak `matthew-henry.zip` uit in dezelfde map als de app.

### Psalmen

Onder **Bijbel → Psalmen** staat het psalmboek: de 150 psalmen in de berijming van 1773, en de Enige Gezangen als de bron die meelevert. Je kiest een psalm, of zoekt op `ps 42:5` of op woorden.

- **Eenmalig ophalen:** dubbelklik op **psalmen-ophalen.bat**. Die haalt de psalmen "zoals de gemeente zingt" uit het open-source programma Stream & Beam van de HHG Tholen, en controleert of alles compleet is (150 psalmen, Psalm 119 met 88 verzen). Lukt dat niet, dan blijft alles zoals het was en meldt het venster waarom.
- **Eigen bestand:** heb je zelf een psalmenbestand (.json of .txt met kopjes "Psalm 1" en genummerde verzen)? Sleep het op psalmen-ophalen.bat.
- **In de live-tekst:** zegt de predikant "we zingen Psalm 42 vers 1 en 5", dan opent een tik op die woorden de berijmde verzen, niet de bijbeltekst.
- **Psalm in de tekst:** achter elke verwijzing naar een psalm staat een extra knopje. Bij een gewone bijbeltekst ("lees Psalm 23") is dat **♪ Psalmboek**, bij "we zingen Psalm 42" is dat **📖 Bijbel**. Zo heb je altijd allebei. In het venster zelf wissel je met de knop onderaan tussen bijbeltekst en berijming. Dit werkt ook in de verklaring van Matthew Henry.
- **Bij de dienst:** staat bij een lied in dienst.json alleen `"titel": "Psalm 42 : 1 en 5"`, dan vult de app de berijmde verzen zelf in.

### Bij de dienst

Wil je voor een dienst de lezingen, liederen of catechismus klaarzetten, vul dan het bestand van die kerk in. In de app verschijnt dan bovenaan een extra tabblad **Bij de dienst**. Is er niets klaargezet, dan zie je alleen de hele Bijbel. Een voorbeeld staat in `data\dienst.voorbeeld.json`.

Bewerk `data/dienst-gergem.json` of `data/dienst-hhg.json` (of `data/dienst.json` voor beide) voor elke dienst. De app neemt wijzigingen direct over, opnieuw starten is niet nodig.

```json
{
  "titel": "Morgendienst", "datum": "2026-11-22", "voorganger": "ds. A. de Vries",
  "onderdelen": [
    { "soort": "lezing", "titel": "Schriftlezing", "verwijzing": "Lukas 15:11-32" },
    { "soort": "lezing", "titel": "Tekst", "verwijzing": "Lukas 15:20", "uitlichten": [20] },
    { "soort": "lied", "titel": "Psalm 103 : 1 en 4", "tekst": "…" },
    { "soort": "catechismus", "titel": "Zondag 7", "vraag": "…", "antwoord": "…" }
  ]
}
```

- Bij een lezing kunt u de tekst zelf invullen met `"tekst"`, of alleen de `verwijzing` geven. In het tweede geval zoekt de app de tekst op in `data/bijbel.json`. Ook afkortingen werken, zoals `Ps 23:1-3`, `Matth. 5:3` en `1 Sam. 3:10`.
- **De complete Statenvertaling ophalen:** dubbelklik eenmalig op **bijbel-ophalen.bat**. Dit downloadt de Statenvertaling in de spelling van statenvertaling.net (publiek domein) en vervangt het voorbeeldbestand. Lukt de download maar half, dan blijft het oude bestand staan.
- Ook de tekst van liederen valt soms onder auteursrecht. De berijming van 1773 en de Psalmen van Datheen zijn vrij te gebruiken.

## 7. Kosten en privacy

- **Spraakherkenning** draait op de laptop zelf. Dat is gratis, en het geluid gaat nergens naartoe.
- **Vertalen met OpenAI** (gpt-4o-mini) kost een paar cent per dienst per taal. U betaalt alleen voor talen die op dat moment door iemand zijn gekozen. De zinnen gaan daarbij naar OpenAI.
- **Gratis en lokaal vertalen** kan met [Ollama](https://ollama.com). De zinnen blijven dan op deze computer. Op een kaart met 16 GB, zoals de RTX PRO 2000 Blackwell, gebruikt u `gemma3:12b`. Die vertaalt goed, en Whisper large-v3 past er gewoon naast. Op een kaart met 8 GB gebruikt u `gemma3:4b`, met `large-v3-turbo` als spraakmodel. Hoe u het instelt, staat in hoofdstuk 1.
- Overleg met de kerkenraad over het bewaren van opnames en teksten. Leg vast hoe lang ze bewaard worden (`bewaar_dagen`).

## 8. Problemen

| Melding of verschijnsel | Oplossing |
|---|---|
| `CUBLAS_STATUS_NOT_SUPPORTED` of 'Videokaart werkt niet' (Blackwell) | Nieuwste NVIDIA-stuurprogramma installeren en installeren.bat opnieuw uitvoeren (cuBLAS 12.8+). Laat `rekentype = "auto"` staan of zet `"float16"`. |
| Vertaling werkt niet met Ollama | Staat Ollama aan (icoon rechtsonder)? Voer controle.bat uit; die zegt of het model ontbreekt. |
| `Videokaart werkt niet … Terugval op de processor` | Werk het NVIDIA-stuurprogramma bij en voer installeren.bat opnieuw uit. Lukt het nog niet, zet dan `engine = "openai"` onder `[spraak]` (ongeveer € 0,35 per uur). |
| Status blijft *Geen uitzending* | Er is op dat moment geen live-uitzending. Controleer anders `stream_url`. |
| Status *Live (vertraagd)* | De herkenning loopt achter op de spraak. Gebruik `large-v3-turbo`. |
| Er verschijnen vreemde zinnen tijdens orgelspel of zang | Verhoog `stilte_drempel`, bijvoorbeeld naar `0.02`. |
| Namen worden verkeerd geschreven | Voeg ze toe aan `woordenlijst`. |
| `conflicting dependencies` / `onnxruntime` | U gebruikt een te nieuwe Python. Voer de nieuwste installeren.bat opnieuw uit; die regelt Python 3.12. |
| `ffmpeg niet gevonden` | Voer installeren.bat opnieuw uit en open daarna een **nieuw** venster. |

Voor meer meldingen in het venster: `start.bat -v`.
