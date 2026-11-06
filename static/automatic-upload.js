(() => {
  const form = document.getElementById('automatic-upload');
  if (!form) return;
  let submitted = false;
  form.querySelector('input[type=file]').addEventListener('change', event => {
    if (event.target.files.length && !submitted) form.requestSubmit();
  });
  form.addEventListener('submit', event => {
    if (submitted) { event.preventDefault(); return; }
    submitted = true;
    const button = form.querySelector('button');
    button.disabled = true;
    button.textContent = 'Uploading…';
  });
})();
