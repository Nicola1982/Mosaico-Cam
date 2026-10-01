# Mosaico Camere

[![Licenza: GPL v3](https://img.shields.io/badge/Licenza-GPLv3-blue.svg)](LICENSE)

Visualizzatore a mosaico per telecamere IP **ONVIF** e **RTSP**, gratuito e open source.
Inserisci (o cerca in rete) le telecamere e le vedi tutte insieme, di qualsiasi marca.

## Funzioni

- **Mosaico adattivo**: la griglia si adatta alla forma della finestra; doppio click per ingrandire una telecamera
- **Ricerca automatica** delle telecamere nella rete (ONVIF e RTSP)
- **Registrazione su disco** nella cartella o nel disco che scegli, anche in **alta definizione** (richiede ffmpeg)
- **Cancellazione automatica** delle registrazioni dopo 24 ore (modificabile)
- **Installer per Windows 10/11**, con disinstallazione dal menu Start
- Funziona offline: nessun cloud, nessun account, nessuna telemetria

## Installazione

1. Vai nella sezione **Releases** e scarica `Setup_MosaicoCamere_1.0.exe`
2. Avvialo e segui la procedura (se Windows mostra l'avviso SmartScreen: *Ulteriori informazioni* → *Esegui comunque*)
3. Apri **Mosaico Camere** e premi **Cerca telecamere**

Per registrare in alta definizione serve **ffmpeg**: l'installer può installarlo per te, oppure il programma te lo propone quando attivi **Registra**.

## Uso rapido

1. **Cerca telecamere**: trova i dispositivi in rete; seleziona quelli che vuoi, inserisci utente e password e premi *Aggiungi selezionate*
2. In alternativa, **+ Aggiungi telecamera** per inserire a mano un dispositivo ONVIF (IP, utente, password) o un URL RTSP
3. Tasto destro su un riquadro per modificare o rimuovere la telecamera
4. **Registra** + **Cartella registrazioni...** per salvare i video dove preferisci

## Compatibilità

Funziona con le telecamere che supportano **ONVIF** o **RTSP**.

| Marca | Note |
|---|---|
| Tapo | Crea un "Account telecamera" nell'app Tapo; RTSP su `stream1` / `stream2`, ONVIF sulla porta 2020 |
| Hikvision | ONVIF/RTSP supportati; su alcuni modelli va abilitato ONVIF nelle impostazioni |
| EZVIZ | Dipende dal modello: molti supportano RTSP/ONVIF in locale, altri sono solo cloud |
| Blink | Non supportata: telecamere solo cloud, senza ONVIF né RTSP |

## Eseguire dal codice sorgente

Serve Python 3.12 o successivo.

```
pip install opencv-python pillow numpy onvif-zeep
python mosaico_cam.py
```

Per creare l'installer su Windows: metti nella stessa cartella `mosaico_cam.py`, `Crea_Installer.bat`, `MosaicoCamere.iss`, `version_info.txt` e i file di licenza, poi esegui `Crea_Installer.bat`. Il risultato è in `installer_out`.

## Licenza

Software libero, distribuito con licenza **GNU GPL versione 3 o successiva** (GPL-3.0-or-later).
Vedi [LICENSE](LICENSE), [CONDIZIONI_USO.txt](CONDIZIONI_USO.txt) e [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt).

> Il programma è fornito senza alcuna garanzia. Usalo solo con telecamere tue o per cui hai autorizzazione, nel rispetto delle norme sulla privacy.

## Assistenza e funzioni premium

Il programma è gratuito. Assistenza, installazione, personalizzazioni e funzioni aggiuntive sono servizi a pagamento, da concordare direttamente con l'autore.

**Contatti:** [[CONTATTO]]

---

© 2026 Murari Nicola
