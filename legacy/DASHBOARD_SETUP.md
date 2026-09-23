# Radio Recorder Dashboard Setup

## Eigenes Dashboard als Unterseite einrichten

### Option 1: Als Custom Panel (Empfohlen)

1. **JavaScript-Datei kopieren:**
   - Kopieren Sie `www/radio-recorder.js` nach `/config/www/radio-recorder.js` in Home Assistant
   - Falls `/config/www/` nicht existiert, erstellen Sie es

2. **Configuration.yaml aktualisieren:**
   - Öffnen Sie `/config/configuration.yaml`
   - Fügen Sie folgendes hinzu:
   ```yaml
   panel_custom:
     - name: radio-recorder
       sidebar_title: Radio Recorder
       sidebar_icon: mdi:radio
       url_path: radio-recorder
       webcomponent_path: /local/radio-recorder.js
       embed_iframe: true
       require_admin: true
   ```

3. **Home Assistant neu starten:**
   - Einstellungen → System → Neustart

4. **Dashboard öffnen:**
   - Das Dashboard ist jetzt über die Sidebar verfügbar: **Radio Recorder**
   - Oder direkt über: `http://homeassistant.local:8123/radio-recorder`

### Option 2: Als separates Dashboard

1. **JavaScript-Datei kopieren:**
   - Kopieren Sie `www/radio-recorder.js` nach `/config/www/radio-recorder.js`

2. **Neues Dashboard erstellen:**
   - Einstellungen → Dashboards → Neues Dashboard
   - Name: "Radio Recorder"
   - URL-Pfad: `radio-recorder`

3. **Custom-Karte hinzufügen:**
   - Karte hinzufügen → Manuell
   - Typ: `custom:panel-frame`
   - URL: `/radio-recorder`

### Option 3: Als Unterseite in bestehendem Dashboard

1. **JavaScript-Datei kopieren:**
   - Kopieren Sie `www/radio-recorder.js` nach `/config/www/radio-recorder.js`

2. **In Lovelace YAML:**
   ```yaml
   type: custom:panel-frame
   url: /radio-recorder
   title: Radio Recorder
   ```

## Standard-Speicherpfad

Das Add-on speichert standardmäßig in `/media/Musick`. Falls dieses Verzeichnis nicht existiert, wird es automatisch erstellt.

## Funktionen des Dashboards

- ✅ Übersicht aller konfigurierten Jobs
- ✅ Anzeige von Job-Details (Zeiten, Stream-URL, Speicherpfad, etc.)
- ✅ Status-Anzeige (Aktiv/Inaktiv)
- ✅ Direkter Link zur Add-on-Konfiguration
- ✅ Automatische Aktualisierung alle 30 Sekunden

## Troubleshooting

**Dashboard wird nicht angezeigt:**
- Prüfen Sie, ob die JavaScript-Datei in `/config/www/` liegt
- Prüfen Sie die `configuration.yaml` auf Syntaxfehler
- Starten Sie Home Assistant neu

**Jobs werden nicht angezeigt:**
- Stellen Sie sicher, dass Jobs in der Add-on-Konfiguration als Liste hinzugefügt wurden
- Prüfen Sie die Browser-Konsole auf Fehler (F12)

