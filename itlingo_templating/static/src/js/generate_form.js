document.addEventListener('submit', async event => {
    const form = event.target;
    if (!form.matches('form[data-generate-form]')) {
        return;
    }
    const feedback = document.getElementById('generate_feedback');
    if (!feedback) {
        form.submit();
        return;
    }

    event.preventDefault();
    const submitter = event.submitter;
    // formAction returns the document URL when formaction is absent; read the content attribute.
    const action = (submitter && submitter.getAttribute('formaction')) || form.action;
    const wasDisabled = submitter && submitter.disabled;
    if (submitter) {
        submitter.disabled = true;
    }
    try {
        const response = await fetch(action, {
            method: 'POST',
            body: new FormData(form),
            credentials: 'same-origin',
        });
        const disposition = response.headers.get('Content-Disposition');
        if (disposition) {
            const match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
                || disposition.match(/filename="?([^";]+)"?/i);
            let filename = 'generated';
            if (match) {
                try {
                    filename = decodeURIComponent(match[1].trim());
                } catch (_) {
                    filename = match[1].trim();
                }
            }
            feedback.innerHTML = '';
            const url = URL.createObjectURL(await response.blob());
            const link = document.createElement('a');
            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            link.remove();
            setTimeout(() => URL.revokeObjectURL(url), 0);
        } else {
            const page = new DOMParser().parseFromString(
                await response.text(), 'text/html',
            );
            const nextFeedback = page.getElementById('generate_feedback');
            if (nextFeedback) {
                feedback.innerHTML = nextFeedback.innerHTML;
            }
            if (!nextFeedback || !nextFeedback.textContent.trim()) {
                feedback.innerHTML = '<div class="alert alert-danger" role="alert">'
                    + 'The server returned no document and no message (HTTP '
                    + response.status + ', URL: ' + action + ').</div>';
            }
            feedback.scrollIntoView({behavior: 'smooth', block: 'center'});
        }
    } catch (_) {
        feedback.innerHTML = '<div class="alert alert-danger" role="alert">'
            + 'Unable to complete the request. Please try again.</div>';
        feedback.scrollIntoView({behavior: 'smooth', block: 'center'});
    } finally {
        if (submitter) {
            submitter.disabled = wasDisabled;
        }
    }
});
