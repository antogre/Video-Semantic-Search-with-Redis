import React, { useState, useEffect, useRef } from 'react';
import './App.css';
import { FiUpload, FiSend, FiLoader, FiExternalLink, FiVideoOff } from 'react-icons/fi';

function App() {
  // --- Stati principali ---
  const [results, setResults] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [backendStatus, setBackendStatus] = useState({});
  const [dbCount, setDbCount] = useState(null);
  
  // --- Stati per UX ---
  const [isSearching, setIsSearching] = useState(false);
  const [isIndexing, setIsIndexing] = useState(false);
  const [searchPerformed, setSearchPerformed] = useState(false);

  // --- Stati per controlli Batch ---
  const [numVideos, setNumVideos] = useState(30);
  const [startPage, setStartPage] = useState(1);

  // useRef per gestire l'intervallo di polling in modo sicuro
  const pollingIntervalRef = useRef(null);

  // Funzione per recuperare lo stato del backend e le statistiche
  const fetchBackendInfo = async () => {
    try {
      const statusResponse = await fetch('http://127.0.0.1:5000/');
      const statusData = await statusResponse.json();
      setBackendStatus(statusData.database_status || {});
      
      const statsResponse = await fetch('http://127.0.0.1:5000/db_stats');
      const statsData = await statsResponse.json();
      setDbCount(statsData.redis);
    } catch (error) {
      console.error("Errore connessione al backend:", error);
      setBackendStatus({ redis: "Error" });
      setDbCount("Error");
    }
  };

  // Esegue il controllo del backend all'avvio e poi a intervalli regolari
  useEffect(() => {
    fetchBackendInfo();
    const intervalId = setInterval(fetchBackendInfo, 30000);
    return () => {
      clearInterval(intervalId);
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current); // Pulisce il polling se il componente viene smontato
      }
    };
  }, []);

  // Gestisce l'upload manuale dei video
  const handleUpload = async (event) => {
    const files = Array.from(event.target.files);
    if (files.length === 0) return;

    setIsIndexing(true);
    let success = false;
    for (const file of files) {
      const formData = new FormData();
      formData.append('video', file, file.name);
      try {
        const res = await fetch('http://127.0.0.1:5000/upload', { method: 'POST', body: formData });
        if (res.ok) success = true;
      } catch (e) {
        console.error(`Upload fallito per ${file.name}:`, e);
      }
    }
    setIsIndexing(false);
    if (success) {
      console.log(`${files.length} video inviati per l'indicizzazione.`);
      fetchBackendInfo();
    }
  };

  // Funzione per il Polling dello Stato dei Task 
  const pollTaskStatus = (taskIds) => {
    pollingIntervalRef.current = setInterval(async () => {
      try {
        const statuses = await Promise.all(
          taskIds.map(id => fetch(`http://127.0.0.1:5000/task_status/${id}`).then(res => res.json()))
        );

        // Controlla se c'è ancora qualche task in esecuzione o in attesa
        const isStillRunning = statuses.some(s => s.status === 'PENDING' || s.status === 'STARTED');

        if (!isStillRunning) {
          console.log('Tutte le task di batch sono completate.');
          clearInterval(pollingIntervalRef.current); 
          setIsIndexing(false); 
          fetchBackendInfo(); 
        }
      } catch (error) {
        console.error("Errore durante il polling dello stato dei task:", error);
        clearInterval(pollingIntervalRef.current);
        setIsIndexing(false);
      }
    }, 3000); 
  };

  // Gestisce l'avvio dell'indicizzazione batch
  const triggerBatch = async () => {
    if (isIndexing || isSearching || backendStatus.redis !== 'OK') return;
    const confirmStart = window.confirm(`Avviare l'indicizzazione di ${numVideos} video partendo da pagina ${startPage}?`);
    if (!confirmStart) return;

    setIsIndexing(true); 
    try {
      const response = await fetch('http://127.0.0.1:5000/trigger_batch_index', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ num_videos: parseInt(numVideos, 10), start_page: parseInt(startPage, 10) })
      });
      const data = await response.json();
      if (response.ok && data.task_ids && data.task_ids.length > 0) {
        console.log("Task di batch inviati. Avvio del polling per gli ID:", data.task_ids);
        pollTaskStatus(data.task_ids); 
      } else {
        console.error(`Errore avvio batch: ${data.error || 'Nessun task ID ricevuto'}`);
        setIsIndexing(false); 
      }
    } catch (error) {
      console.error(`Errore network batch:`, error);
      setIsIndexing(false); 
    }
  };
  
  // Gestisce la ricerca semantica
  const handleSearch = async () => {
    if (!searchQuery.trim() || backendStatus.redis !== 'OK') return;
    
    setIsSearching(true);
    setSearchPerformed(true);
    setResults([]);

    try {
      const response = await fetch('http://127.0.0.1:5000/search', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchQuery, k: 12 }),
      });
      const data = await response.json();
      if (response.ok) {
        setResults(data.results || []);
      } else {
        console.error(`Errore Ricerca: ${data.error || 'Risposta non valida'}`);
      }
    } catch (error) {
      console.error(`Errore di Rete:`, error);
    }
    setIsSearching(false);
  };
  
  // Gestisce l'invio con il tasto Invio
  const handleKeyDown = (event) => {
    if (event.key === 'Enter') handleSearch();
  };
  
  // Gestisce la modifica dell'input di ricerca
  const handleSearchInputChange = (e) => {
    setSearchQuery(e.target.value);
    if(e.target.value === '') {
        setSearchPerformed(false);
        setResults([]);
    }
  };

  const isServiceReady = backendStatus.redis === 'OK';
  const anyLoading = isSearching || isIndexing;

  return (
    <div className="app">
      <header className="header">
        <h1>Video Semantic Search</h1>
        <div className="db-status">
          <span className={`status-pill ${isServiceReady ? 'ok' : 'error'}`} title={backendStatus.redis}>
            Redis: {dbCount !== null ? dbCount : '?'}
          </span>
        </div>
      </header>

      <main className="main">
        <label htmlFor="manual-upload-input" className={`upload-button ${!isServiceReady || anyLoading ? 'disabled' : ''}`}>
           <FiUpload/> Carica Video
        </label>
        <input type="file" id="manual-upload-input" accept="video/*" multiple style={{ display: 'none' }} onChange={handleUpload} disabled={!isServiceReady || anyLoading} />

        <div className="batch-controls">
            <div className="batch-input-group">
                <label htmlFor="num-videos">Num. Video</label>
                <input id="num-videos" type="number" value={numVideos} onChange={(e) => setNumVideos(e.target.value)} min="1" disabled={!isServiceReady || anyLoading}/>
            </div>
            <div className="batch-input-group">
                <label htmlFor="start-page">Pagina Inizio</label>
                <input id="start-page" type="number" value={startPage} onChange={(e) => setStartPage(e.target.value)} min="1" disabled={!isServiceReady || anyLoading}/>
            </div>
            <button onClick={triggerBatch} disabled={!isServiceReady || anyLoading} className="batch-button">
              Avvia Batch API
            </button>
        </div>
      </main>
      
      <div className="results-container">
        {isSearching && (
          <div className="loading-placeholder"><FiLoader className="spinner" size={32} /> Ricerca in corso...</div>
        )}
        {isIndexing && (
            <div className="loading-placeholder">
                <FiLoader className="spinner" size={32} />
                <span>Estrazione embedding e indicizzazione in corso...</span>
            </div>
        )}
        
        {!anyLoading && results.length > 0 && (
          <div className="video-grid">
            {results.map((video, index) => (
              <div className="video-item" key={`${video.name}-${index}`}>
                <div className="video-placeholder"><FiVideoOff size={40} /></div>
                <p className="video-name" title={video.name}>{video.name || 'Nome non disponibile'}</p>
                {video.source_url && (
                   <p className="video-backend-url">
                     <a href={video.source_url} target="_blank" rel="noopener noreferrer">Link al video <FiExternalLink size={12} /></a>
                   </p>
                )}
                <p className="video-similarity">Distance: {video.similarity?.toFixed(4)}</p>
              </div>
            ))}
          </div>
        )}
        {!anyLoading && results.length === 0 && searchPerformed && (
          <p className="db-message">Nessun risultato trovato per "{searchQuery}".</p>
        )}
      </div>

      <div className="search-bar">
        <input
          type="text"
          placeholder={isServiceReady ? "Cerca tra i tuoi video..." : "Servizio non disponibile"}
          value={searchQuery}
          onChange={handleSearchInputChange}
          onKeyDown={handleKeyDown}
          disabled={anyLoading || !isServiceReady}
        />
        <span className="search-icon" onClick={!anyLoading && isServiceReady ? handleSearch : undefined} style={{ cursor: (!anyLoading && isServiceReady) ? 'pointer' : 'not-allowed' }}>
          {isSearching ? <FiLoader className="spinner" size={20} /> : <FiSend size={20} />}
        </span>
      </div>

      <footer className="footer">
        <p>Creato da Antonio</p>
      </footer>
    </div>
  );
}

export default App;
