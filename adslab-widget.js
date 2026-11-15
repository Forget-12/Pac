
(function() {
    // 1. Inject Widget Styles
    const style = document.createElement('style');
    style.innerHTML = `
        .alcaptcha-container {
            position: relative;
            width: 300px;
            height: 100px;
            margin: 10px 0;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #fafafa;
            border: 1px solid #d1d5db;
            border-radius: 4px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            font-family: system-ui, -apple-system, sans-serif;
            transition: background 0.3s ease, border-color 0.3s ease;
        }
        
        .alcaptcha-start-ui {
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            padding: 0 20px;
            gap: 15px;
            cursor: pointer;
            z-index: 10;
            transition: opacity 0.3s ease;
            background: transparent;
        }
        .alcaptcha-start-ui:hover {
            background: #f3f4f6;
        }
        
        .alfp-6923d8cf {
            position: relative;
            width: 56px;
            height: 56px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            background: #f3f4f6;
            flex-shrink: 0;
        }
        .alic-f6387678 {
            width: 32px;
            height: 32px;
            color: #4b5563;
            z-index: 2;
        }
        .alr-f74cfdea {
            position: absolute;
            top: 0; left: 0;
            width: 56px; height: 56px;
            transform: rotate(-90deg);
        }
        .alr-f74cfdea circle {
            fill: transparent;
            stroke: #3b82f6;
            stroke-width: 3.5;
            stroke-dasharray: 157.1;
            stroke-dashoffset: 157.1;
            transition: stroke-dashoffset 0.1s linear;
        }
        .alcaptcha-start-ui:hover .alfp-6923d8cf {
            background: #e5e7eb;
        }
        
        .alcaptcha-text {
            color: #4b5563;
            font-size: 13px;
            font-weight: 500;
            user-select: none;
            -webkit-user-select: none;
            line-height: 1.2;
        }
        
        .alcaptcha-iframe {
            opacity: 0;
            position: absolute;
            top: 0; left: 0;
            width: 300px !important;
            height: 100px !important;
            pointer-events: none;
            transition: opacity 0.3s ease;
            z-index: 5;
        }
        .alcaptcha-iframe.al-show {
            opacity: 1;
            pointer-events: auto;
            z-index: 20;
        }
        
        .alcaptcha-success {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            color: #059669;
            font-weight: 600;
            font-size: 16px;
            opacity: 0;
            position: absolute;
            inset: 0;
            pointer-events: none;
            transition: opacity 0.4s ease;
            z-index: 30;
        }
        .alcaptcha-success.al-show {
            opacity: 1;
        }
        .alcaptcha-success svg {
            width: 28px; height: 28px;
        }
        
        .adslab-badge-embed {
            position: absolute;
            top: 0; right: 0; z-index: 100;
            display: flex; align-items: center; justify-content: flex-start;
            background: #ffffff;
            overflow: hidden;
            height: 25px; width: 25px;
            border-bottom-left-radius: 6px;
            text-decoration: none;
            transition: width 0.3s ease-in-out;
            box-shadow: 0 1px 2px rgba(0,0,0,0.05);
            border-left: 1px solid #e5e7eb;
            border-bottom: 1px solid #e5e7eb;
        }
        .adslab-badge-embed:hover {
            width: 125px;
        }
        .badge-icon {
            display: flex; align-items: center; justify-content: center;
            width: 25px; flex-shrink: 0;
        }
        .badge-text {
            color: #000; font-family: sans-serif; font-size: 11px; font-weight: bold;
            white-space: nowrap; opacity: 0; transition: opacity 0.2s ease; padding-right: 8px;
        }
        .adslab-badge-embed:hover .badge-text {
            opacity: 1;
        }
    `;
    document.head.appendChild(style);

    window.initALCaptcha = initALCaptcha;
    function initALCaptcha() {
        const containers = document.querySelectorAll('.adslab-captcha');
        containers.forEach(container => {
            if (container.dataset.initialized) return;
            const sitekey = container.getAttribute('data-sitekey');
            if (!sitekey) {
                console.error("ALCaptcha: Missing data-sitekey attribute.");
                return;
            }
            const subid = container.getAttribute('data-subid') || 'widget_user';
            
            const wrapper = document.createElement('div');
            wrapper.className = 'alcaptcha-container';

            // Start UI (Hold Fingerprint & Text)
            const startUi = document.createElement('div');
            startUi.className = 'alcaptcha-start-ui';
            
            const fpWrapper = document.createElement('div');
            fpWrapper.className = 'alfp-6923d8cf';
            fpWrapper.innerHTML = `
                <svg class="alr-f74cfdea" viewBox="0 0 56 56">
                    <circle cx="28" cy="28" r="25"></circle>
                </svg>
                <svg class="alic-f6387678" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 008 11a4 4 0 118 0c0 1.017-.07 2.019-.203 3m-2.118 6.844A21.88 21.88 0 0015.171 17m3.839 1.132c.645-2.266.99-4.659.99-7.132A8 8 0 008 4.07M3 15.364c.64-1.319 1-2.8 1-4.364 0-1.457.39-2.823 1.07-4"></path></svg>
            `;
            
            const text = document.createElement('span');
            text.className = 'alcaptcha-text';
            text.innerText = 'Please hold the click on the fingerprint to load the captcha';
            
            startUi.appendChild(fpWrapper);
            startUi.appendChild(text);

            // Iframe (Loaded in background to be fast, but hidden)
            const iframe = document.createElement('iframe');
            const parentDomain = window.location.hostname;
            iframe.src = `https://adslab.me/alcaptcha?sitekey=` + encodeURIComponent(sitekey) + '&domain=' + encodeURIComponent(parentDomain) + '&subid=' + encodeURIComponent(subid);
            iframe.title = 'ALCaptcha Widget';
            iframe.width = "300";
            iframe.height = "100";
            iframe.style.border = "none";
            iframe.style.overflow = "hidden";
            iframe.title = "ALCaptcha Widget";
            iframe.className = "alcaptcha-iframe";
            
            // Success Message
            const successMsg = document.createElement('div');
            successMsg.className = 'alcaptcha-success';
            successMsg.innerHTML = `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"></path></svg> <span>Successful verification!</span>`;
            
            // Badge
            const badge = document.createElement('a');
            badge.href = "https://adslab.me";
            badge.target = "_blank";
            badge.className = "adslab-badge-embed";
            badge.innerHTML = `
                <span class="badge-icon">
                    <img src="https://cdn.adslab.me/adchoices/alicon.svg" style="width:14px;height:14px;display:block;" alt="AdsLab" />
                </span>
                <span class="badge-text">AdsLab Captcha</span>
            `;
            
            wrapper.appendChild(startUi);
            wrapper.appendChild(iframe);
            wrapper.appendChild(successMsg);
            wrapper.appendChild(badge);
            container.appendChild(wrapper);
            container.dataset.initialized = "true";

            // Hold Logic
            let holdTimer = null;
            let progress = 0;
            const HOLD_TIME = 1000;
            const INTERVAL = 50;
            const circle = fpWrapper.querySelector('circle');
            
            function startHold(e) {
                if (e && e.cancelable) e.preventDefault();
                if (e && !e.isTrusted) return; // Block synthetic events
                if (wrapper.dataset.solved || wrapper.dataset.waitingForLoad === 'true') return;
                
                clearInterval(holdTimer);
                holdTimer = setInterval(() => {
                    progress += INTERVAL;
                    const percent = Math.min(progress / HOLD_TIME, 1);
                    circle.style.strokeDashoffset = 157.1 * (1 - percent);
                    
                    if (progress >= HOLD_TIME) {
                        clearInterval(holdTimer);
                        completeHold();
                    }
                }, INTERVAL);
            }
            
            function stopHold() {
                if (wrapper.dataset.waitingForLoad === 'true') return;
                clearInterval(holdTimer);
                progress = 0;
                circle.style.strokeDashoffset = 157.1;
            }
            
            function completeHold() {
                text.innerText = 'Loading secure challenge...';
                startUi.style.pointerEvents = 'none';
                
                if (iframe.dataset.isLoaded === 'true') {
                    showChallenge();
                } else {
                    wrapper.dataset.waitingForLoad = 'true';
                }
            }

            startUi.addEventListener('mousedown', startHold);
            startUi.addEventListener('touchstart', startHold, {passive: false});
            
            window.addEventListener('mouseup', stopHold);
            startUi.addEventListener('mouseleave', stopHold);
            window.addEventListener('touchend', stopHold);

            function showChallenge() {
                startUi.style.opacity = '0';
                setTimeout(() => {
                    startUi.style.display = 'none';
                    iframe.classList.add('al-show');
                }, 300);
            }

            // We keep a reference to showChallenge on the wrapper so the message listener can call it
            wrapper.showChallenge = showChallenge;
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initALCaptcha);
    } else {
        initALCaptcha();
    }

    // Handle Back/Forward cache (BFCache)
    window.addEventListener('pageshow', function(event) {
        if (event.persisted) {
            initALCaptcha();
        }
    });

    window.addEventListener('message', function(event) {
        if (event.data && event.data.type === 'ALCAPTCHA_LOADED') {
            const containers = document.querySelectorAll('.adslab-captcha');
            containers.forEach(container => {
                const wrapper = container.querySelector('.alcaptcha-container');
                if (!wrapper) return;
                const iframe = wrapper.querySelector('iframe');
                
                if (iframe) {
                    iframe.dataset.isLoaded = 'true';
                    // If user already clicked and is waiting, show it now!
                    if (wrapper.dataset.waitingForLoad === 'true') {
                        wrapper.dataset.waitingForLoad = 'false';
                        if (wrapper.showChallenge) wrapper.showChallenge();
                    }
                }
            });
        }

        if (event.data && event.data.type === 'ALCAPTCHA_SOLVED') {
            const token = event.data.token;
            
            const containers = document.querySelectorAll('.adslab-captcha');
            containers.forEach(container => {
                const wrapper = container.querySelector('.alcaptcha-container');
                if (!wrapper) return;
                
                if (wrapper.dataset.solved) return;
                wrapper.dataset.solved = "true";

                const targetElement = container.closest('form') || container;
                
                const existing = targetElement.querySelector('input[name="alcaptcha-response"]');
                if (existing) existing.remove();
                
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'alcaptcha-response';
                input.value = token;
                targetElement.appendChild(input);
                
                const iframe = wrapper.querySelector('iframe');
                const successMsg = wrapper.querySelector('.alcaptcha-success');
                const startUi = wrapper.querySelector('.alcaptcha-start-ui');
                
                if (iframe) iframe.classList.remove('al-show');
                if (startUi) startUi.style.display = 'none';
                
                wrapper.style.background = '#ecfdf5';
                wrapper.style.borderColor = '#10b981';
                
                setTimeout(() => {
                    if (iframe) iframe.style.display = 'none';
                    if (successMsg) successMsg.classList.add('al-show');
                }, 300);
            });
            
            window.dispatchEvent(new CustomEvent('alcaptcha-success', { detail: { token: token } }));
        }
    });
})();
    