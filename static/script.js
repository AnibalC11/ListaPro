/* ===== PHOTO PREVIEW ===== */
const fotosInput = document.getElementById('fotos');
const photoPreview = document.getElementById('photo-preview');
const fileDropArea = document.getElementById('file-drop-area');

fotosInput.addEventListener('change', () => {
  photoPreview.innerHTML = '';
  const files = Array.from(fotosInput.files);
  if (files.length === 0) {
    photoPreview.classList.add('hidden');
    return;
  }
  photoPreview.classList.remove('hidden');
  files.forEach((file, i) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const img = document.createElement('img');
      img.src = e.target.result;
      img.alt = file.name;
      if (i === 0) img.classList.add('cover');
      photoPreview.appendChild(img);
    };
    reader.readAsDataURL(file);
  });
  // Update drop area label
  const label = fileDropArea.querySelector('span:not(.file-icon)');
  if (label) label.innerHTML = `<strong>${files.length} foto(s) seleccionada(s)</strong>`;
});

// Drag & drop styling
fileDropArea.addEventListener('dragover', (e) => { e.preventDefault(); fileDropArea.style.borderColor = '#1a3a5c'; });
fileDropArea.addEventListener('dragleave', () => { fileDropArea.style.borderColor = ''; });
fileDropArea.addEventListener('drop', () => { fileDropArea.style.borderColor = ''; });


/* ===== FORM SUBMIT ===== */
const form = document.getElementById('property-form');
const loadingOverlay = document.getElementById('loading-overlay');
const resultsSection = document.getElementById('results-section');
const submitBtn = document.getElementById('submit-btn');
const btnText = document.getElementById('btn-text');
const btnSpinner = document.getElementById('btn-spinner');

form.addEventListener('submit', async (e) => {
  e.preventDefault();

  if (!validateForm()) return;

  // Show loading
  loadingOverlay.classList.remove('hidden');
  submitBtn.disabled = true;
  btnText.textContent = 'Generando...';
  btnSpinner.classList.remove('hidden');

  const formData = new FormData(form);

  try {
    const response = await fetch('/generate', {
      method: 'POST',
      body: formData,
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || 'Error del servidor');
    }

    renderResults(data);

  } catch (err) {
    alert('Error al generar contenido: ' + err.message);
  } finally {
    loadingOverlay.classList.add('hidden');
    submitBtn.disabled = false;
    btnText.textContent = '✨ Generar con IA';
    btnSpinner.classList.add('hidden');
  }
});


/* ===== RENDER RESULTS ===== */
function renderResults(data) {
  lastResult = data;
  // Populate texts
  document.getElementById('descripcion-text').textContent = data.descripcion;
  document.getElementById('instagram-text').textContent = data.instagram;

  // Foto portada
  const fotoResult = document.getElementById('foto-result');
  if (data.foto_portada) {
    document.getElementById('foto-portada-img').src = data.foto_portada;
    fotoResult.classList.remove('hidden');
  } else {
    fotoResult.classList.add('hidden');
  }

  // Agente
  if (data.agente) {
    document.getElementById('agente-nombre').textContent = data.agente.nombre;
    document.getElementById('agente-contacto').textContent =
      `${data.agente.telefono} · ${data.agente.email}`;
  }

  // Hide form, show results
  form.classList.add('hidden');
  resultsSection.classList.remove('hidden');

  // Smooth scroll to top of results
  resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}


/* ===== COPY TO CLIPBOARD ===== */
document.querySelectorAll('.btn-copy').forEach((btn) => {
  btn.addEventListener('click', async () => {
    const targetId = btn.dataset.target;
    const text = document.getElementById(targetId)?.textContent;
    if (!text) return;

    try {
      await navigator.clipboard.writeText(text);
      const original = btn.textContent;
      btn.textContent = '¡Copiado!';
      btn.classList.add('copied');
      setTimeout(() => {
        btn.textContent = original;
        btn.classList.remove('copied');
      }, 2000);
    } catch {
      // Fallback for older browsers
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      btn.textContent = '¡Copiado!';
      btn.classList.add('copied');
      setTimeout(() => {
        btn.textContent = 'Copiar';
        btn.classList.remove('copied');
      }, 2000);
    }
  });
});


/* ===== DOWNLOAD PDF ===== */
let lastResult = null;

document.getElementById('btn-pdf').addEventListener('click', async () => {
  if (!lastResult) return;

  const btnPdf = document.getElementById('btn-pdf');
  const btnPdfText = document.getElementById('btn-pdf-text');
  const btnPdfSpinner = document.getElementById('btn-pdf-spinner');

  btnPdf.disabled = true;
  btnPdfText.textContent = 'Generando PDF...';
  btnPdfSpinner.classList.remove('hidden');

  try {
    const response = await fetch('/generate-pdf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(lastResult),
    });

    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || 'Error al generar PDF');
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const tipo = lastResult.propiedad?.tipo || 'propiedad';
    const ciudad = lastResult.propiedad?.ciudad_estado || '';
    a.download = `ListaPro_${tipo}_${ciudad}.pdf`.replace(/\s+/g, '_');
    a.href = url;
    a.click();
    URL.revokeObjectURL(url);

  } catch (err) {
    alert('Error al generar el PDF: ' + err.message);
  } finally {
    btnPdf.disabled = false;
    btnPdfText.textContent = '⬇ Descargar PDF';
    btnPdfSpinner.classList.add('hidden');
  }
});


/* ===== DOWNLOAD INSTAGRAM IMAGE ===== */
document.getElementById('btn-instagram-img').addEventListener('click', async () => {
  if (!lastResult) return;

  const btn = document.getElementById('btn-instagram-img');
  const btnText = document.getElementById('btn-ig-text');
  const btnSpinner = document.getElementById('btn-ig-spinner');

  btn.disabled = true;
  btnText.textContent = 'Generando imagen...';
  btnSpinner.classList.remove('hidden');

  try {
    const response = await fetch('/generate-instagram-image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(lastResult),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Error al generar imagen');
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const tipo = lastResult.propiedad?.tipo || 'propiedad';
    const ciudad = lastResult.propiedad?.ciudad_estado || '';
    a.download = `ListaPro_Instagram_${tipo}_${ciudad}.jpg`.replace(/\s+/g, '_');
    a.href = url;
    a.click();
    URL.revokeObjectURL(url);

  } catch (err) {
    alert('Error al generar la imagen: ' + err.message);
  } finally {
    btn.disabled = false;
    btnText.textContent = '📷 Imagen Instagram';
    btnSpinner.classList.add('hidden');
  }
});


/* ===== TOAST ===== */
function showToast(msg, type = 'success') {
  const toast = document.getElementById('toast');
  document.getElementById('toast-icon').textContent = type === 'success' ? '✅' : '❌';
  document.getElementById('toast-msg').textContent  = msg;
  toast.className = `toast ${type}`;
  toast.classList.remove('hidden');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => toast.classList.add('hidden'), 5000);
}


/* ===== PUBLISH TO INSTAGRAM ===== */
document.getElementById('btn-publish-ig').addEventListener('click', async () => {
  if (!lastResult) return;

  const btn       = document.getElementById('btn-publish-ig');
  const btnText   = document.getElementById('btn-pub-text');
  const btnSpinner = document.getElementById('btn-pub-spinner');

  btn.disabled = true;
  btnText.textContent = 'Publicando...';
  btnSpinner.classList.remove('hidden');

  try {
    const res = await fetch('/publish-instagram', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(lastResult),
    });
    const json = await res.json();
    if (res.ok && json.ok) {
      showToast(json.message, 'success');
    } else {
      showToast(json.error || 'Error al publicar en Instagram', 'error');
    }
  } catch (err) {
    showToast('Error de conexión: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btnText.textContent = '🚀 Publicar en Instagram';
    btnSpinner.classList.add('hidden');
  }
});


/* ===== GENERATE VIDEO ===== */
document.getElementById('btn-video').addEventListener('click', async () => {
  if (!lastResult) {
    showToast('Primero genera el contenido con IA', 'error');
    return;
  }

  const btn        = document.getElementById('btn-video');
  const btnText    = document.getElementById('btn-video-text');
  const btnSpinner = document.getElementById('btn-video-spinner');
  const modal      = document.getElementById('video-progress-modal');
  const bar        = document.getElementById('vp-bar');
  const pct        = document.getElementById('vp-pct');

  btn.disabled = true;
  btnText.textContent = 'Iniciando...';
  btnSpinner.classList.remove('hidden');

  let pollTimer = null;

  function stopPoll() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function setProgress(value) {
    bar.style.width = value + '%';
    pct.textContent = value + '%';
  }

  function closeModal() {
    modal.classList.add('hidden');
    setProgress(0);
  }

  try {
    const startRes  = await fetch('/generate-video', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(lastResult),
    });
    const startData = await startRes.json();
    if (!startRes.ok) throw new Error(startData.error || 'Error al iniciar render');

    const { render_id } = startData;

    // Mostrar modal de progreso
    modal.classList.remove('hidden');
    btnText.textContent = '🎬 Generar Video';
    btnSpinner.classList.add('hidden');

    // Polling cada 2 segundos
    pollTimer = setInterval(async () => {
      try {
        const res  = await fetch(`/render-status/${render_id}`);
        const task = await res.json();

        setProgress(task.progress || 0);

        if (task.status === 'done') {
          stopPoll();
          setProgress(100);

          // Pequeña pausa para que el usuario vea el 100 %
          setTimeout(() => {
            closeModal();
            btn.disabled = false;

            // Descarga automática del MP4
            const a     = document.createElement('a');
            const tipo  = lastResult.propiedad?.tipo  || 'propiedad';
            const ciudad= lastResult.propiedad?.ciudad_estado || '';
            a.href     = task.output_file;
            a.download = `ListaPro_Reel_${tipo}_${ciudad}.mp4`.replace(/\s+/g, '_');
            a.click();

            showToast('¡Video generado y descargado!', 'success');
          }, 700);

        } else if (task.status === 'error') {
          stopPoll();
          closeModal();
          btn.disabled = false;
          showToast('Error al generar el video: ' + (task.error || 'desconocido'), 'error');
        }

      } catch (pollErr) {
        stopPoll();
        closeModal();
        btn.disabled = false;
        showToast('Error de conexión durante el render', 'error');
      }
    }, 2000);

  } catch (err) {
    stopPoll();
    closeModal();
    btn.disabled = false;
    btnText.textContent = '🎬 Generar Video';
    btnSpinner.classList.add('hidden');
    showToast('Error: ' + err.message, 'error');
  }
});


/* ===== RESTART ===== */
document.getElementById('btn-restart').addEventListener('click', () => {
  resultsSection.classList.add('hidden');
  form.classList.remove('hidden');
  // Optionally reset form
  // form.reset();
  // photoPreview.innerHTML = '';
  // photoPreview.classList.add('hidden');
  window.scrollTo({ top: 0, behavior: 'smooth' });
});


/* ===== BASIC VALIDATION ===== */
function validateForm() {
  const required = form.querySelectorAll('[required]');
  for (const field of required) {
    if (!field.value.trim()) {
      field.focus();
      field.style.borderColor = 'var(--error)';
      field.addEventListener('input', () => { field.style.borderColor = ''; }, { once: true });
      showValidationMsg(field, 'Este campo es obligatorio');
      return false;
    }
  }

  // Check radio operacion
  const operacion = form.querySelector('input[name="operacion"]:checked');
  if (!operacion) {
    alert('Por favor selecciona el tipo de operación (Venta o Alquiler)');
    return false;
  }

  // Check at least one photo
  if (fotosInput.files.length === 0) {
    fotosInput.closest('.form-group').querySelector('label').style.color = 'var(--error)';
    alert('Por favor sube al menos una foto de la propiedad');
    return false;
  }

  return true;
}

function showValidationMsg(field, msg) {
  // Remove existing message
  const existing = field.parentElement.querySelector('.validation-msg');
  if (existing) existing.remove();

  const span = document.createElement('span');
  span.className = 'validation-msg';
  span.style.cssText = 'color: var(--error); font-size: 0.80rem; margin-top: 2px;';
  span.textContent = msg;
  field.parentElement.appendChild(span);

  field.addEventListener('input', () => span.remove(), { once: true });
}
