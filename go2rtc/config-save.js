// Product integration for the packaged official editor; upstream stays pinned.
export async function saveGo2rtcConfig(editor, previous, saved) {
    const signal = AbortSignal.timeout(30000);
    const options = {cache: 'no-store', credentials: 'same-origin', signal};
    let persisted = false;
    try {
        const current = await fetch('api/config', options);
        if (!current.ok) throw new Error('无法读取配置，请检查登录、权限和 go2rtc 状态。');
        if (previous !== await current.text()) {
            alert('Config was changed from another place. Refresh the page and make changes again');
            return;
        }
        // Keep the exact submitted snapshot: editing during the request must
        // remain an unsaved draft, not become the next conflict-check baseline.
        const value = editor.getValue();
        const response = await fetch('api/config', {...options, method: 'POST', body: value});
        if (!response.ok) throw new Error('配置未保存，请检查 YAML 格式及配置文件是否可写。');
        persisted = true;
        saved(value);
        const restart = await fetch('api/restart', {...options, method: 'POST'});
        if (!restart.ok) throw new Error('重载请求失败。');
        while (!signal.aborted) {
            const active = await fetch('api/streams', options).catch(() => null);
            if (active?.ok) {
                await active.json();
                if (window.parent !== window)
                    window.parent.postMessage({type: 'webobs:go2rtc-reloaded'}, location.origin);
                alert('配置已保存并生效 / Configuration saved and loaded');
                return;
            }
            await new Promise(resolve => setTimeout(resolve, 250));
        }
        throw new Error('重载等待超时。');
    } catch (error) {
        alert(persisted
            ? '配置已写入，但重载尚未确认。请检查 go2rtc 状态后再次保存并重启。 / Saved, but reload is unconfirmed. Check go2rtc and retry Save & Restart.'
            : error.name === 'TimeoutError'
                ? '保存请求超时，结果尚未确认。请刷新并核对配置。 / Save timed out; refresh and check the configuration.'
                : error.message);
    }
}
