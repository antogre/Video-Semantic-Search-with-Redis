# Ricerca Semantica di Video con CLIP e Redis

Questo progetto implementa un sistema avanzato per la ricerca di video basata sul loro contenuto semantico. Utilizza il modello di intelligenza artificiale CLIP4CLIP per generare embedding sia per i video che per le query testuali. Questi embedding vengono memorizzati e indicizzati in un database vettoriale Redis, permettendo ricerche per similarità estremamente rapide ed efficaci.

L'utente può cercare un video descrivendo a parole cosa contiene (es. "un cane che gioca sulla spiaggia") e il sistema restituirà i video più pertinenti.

---

## Architettura

Il sistema è basato su microservizi e containerizzato con Docker. I componenti principali sono:

* **Frontend**: Un'interfaccia utente Costruita con **React**, che permette di caricare video, avviare l'indicizzazione e visualizzare i risultati di ricerca.
* **Backend API**: Un'API REST sviluppata con **Flask** che gestisce le richieste HTTP, l'upload dei file e l'interazione con il sistema di task.
* **Worker Asincrono**: Un worker **Celery** che gestisce le operazioni lunghe e computazionalmente intensive come il download e l'estrazione degli embedding dei video in background, senza bloccare l'interfaccia utente.
* **Database & Broker**: Un singolo container **Redis Stack** che funge da:
    1.  **Database Vettoriale** grazie al modulo RediSearch, per l'indicizzazione e la ricerca degli embedding.
    2.  **Broker** per Celery, gestendo la coda dei compiti tra l'API e i worker.

---

## Prerequisiti

Per eseguire questo progetto è necessario avere installato sul proprio computer:

* [**Docker Desktop**](https://www.docker.com/products/docker-desktop/)

---

## Configurazione

Prima di avviare il progetto, sono necessari due passaggi di configurazione.

### 1. File di Servizio Google

Questo progetto utilizza un'API esterna che richiede autenticazione tramite un Service Account di Google.

* Ottieni il tuo file `service_account.json`.
* Posiziona questo file all'interno della cartella `/container1-backend/`.

### 2. Memoria per Docker

Il modello di intelligenza artificiale caricato dal worker (`celery-worker`) richiede una quantità significativa di RAM. È fondamentale aumentare la memoria allocata a Docker Desktop per evitare che il container del worker venga terminato dal sistema.

1.  Apri le **Impostazioni** di Docker Desktop.
2.  Vai alla sezione **Risorse**.
3.  Aumenta lo slider della **Memoria** ad almeno **4 GB** (consigliato 6-8 GB se disponibili).
4.  Clicca su **"Apply & Restart"**.

---

## Avvio e Utilizzo

Una volta completata la configurazione, segui questi passaggi:

1.  Apri un terminale nella cartella principale del progetto (dove si trova il file `docker-compose.yml`).
2.  Esegui il seguente comando per costruire le immagini e avviare tutti i container:

    ```bash
    docker-compose up --build
    ```

3.  Attendi che tutti i servizi siano partiti. Vedrai i log scorrere nel terminale.
4.  Apri il tuo browser e vai all'indirizzo:

    `http://localhost:3000`

### Funzionalità

Dall'interfaccia utente puoi:

* **Caricare Video Manualmente**: Clicca su "Carica Video" per selezionare uno o più file video dal tuo computer. Questi verranno indicizzati immediatamente.
* **Avviare l'Indicizzazione Batch**:
    * Imposta il numero di video da indicizzare e la pagina da cui partire.
    * Clicca su "Avvia Batch API" per avviare il processo in background. Potrai monitorare l'avanzamento dai log del container `celery-worker-1`.
* **Cercare Video**: Scrivi una descrizione testuale (es. "una persona che balla") nella barra di ricerca e premi Invio o clicca sull'icona di invio per trovare i video corrispondenti.
