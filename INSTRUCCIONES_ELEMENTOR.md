# Configuración Elementor + GTM para el webhook IM

## 1. Capturar gclid en cookie (vía GTM)

En GTM (`GTM-P24M67C`), crear un nuevo **Tag** tipo "Custom HTML":

- Nombre: `Capture GCLID Cookie`
- Trigger: All Pages
- HTML:

```html
<script>
(function() {
  function getParam(name) {
    var u = new URL(window.location.href);
    return u.searchParams.get(name);
  }
  function setCookie(name, value, days) {
    var d = new Date();
    d.setTime(d.getTime() + (days * 24 * 60 * 60 * 1000));
    document.cookie = name + "=" + value + ";expires=" + d.toUTCString() + ";path=/;SameSite=Lax;Secure";
  }
  function getCookie(name) {
    var match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
    return match ? match[2] : null;
  }
  ["gclid", "wbraid", "gbraid"].forEach(function(key) {
    var v = getParam(key);
    if (v) setCookie(key, v, 90);
  });
  // Rellenar campos ocultos del form Elementor con el valor de la cookie
  document.addEventListener("DOMContentLoaded", function() {
    ["gclid", "wbraid", "gbraid"].forEach(function(key) {
      var v = getCookie(key);
      if (!v) return;
      document.querySelectorAll('input[name="form_fields[' + key + ']"]').forEach(function(el) {
        el.value = v;
      });
    });
  });
})();
</script>
```

Publicar el container GTM tras guardar.

---

## 2. Editar el form "Form servicios 2026" en Elementor

Ir a **wp-admin → Pages → Venta de despachos** (o donde viva la landing) → editar con Elementor.

### 2.1 Añadir Hidden field `gclid`

Click en el widget del Form. En el panel izquierdo:

- Tab **Content → Form Fields** → Add Item:
  - **Type**: Hidden
  - **Label**: `gclid` (no se muestra, pero ayuda a identificar)
  - **ID**: `gclid` ← IMPORTANTE: ID exactamente `gclid` (sin mayúsculas, sin espacios)
  - **Default Value**: dejar vacío (GTM lo rellena)

(Opcional, recomendado: repetir para `wbraid` y `gbraid` — son los IDs de click cuando el gclid no aplica, ej. iOS App Tracking).

### 2.2 Configurar Webhook como Submit Action

En el mismo widget del Form:

- Tab **Content → Actions After Submit** → marcar **Webhook** (manteniendo Email y MailChimp si ya estaban).
- Bajar a la sección **Webhook**:
  - **Webhook URL**: `https://izquierdomotter-webhook.a7lflv.easypanel.host/webhook/elementor`
  - **Advanced Data**: ON (para que mande también metadata del form).

Elementor Pro por defecto NO permite añadir headers custom. Por eso el secret lo enviaremos como **query string** en la URL:

→ URL final: `https://izquierdomotter-webhook.a7lflv.easypanel.host/webhook/elementor?secret=ABCDEF123456`

(El secret exacto te lo paso una vez deployado el servicio.)

### 2.3 Guardar y publicar

Botón **Update** arriba a la derecha en Elementor.

---

## 3. Test end-to-end

1. Abre en navegador privado: `https://izquierdomotter.com/venta-de-despachos/?gclid=test_webhook_001`
2. Rellena el form con email `test+webhook@uptomarketing.com` y teléfono `600000000`.
3. Envía.
4. Yo verifico en logs del servicio EasyPanel + en Google Ads → Tools → Conversions → Uploads (aparece como "Click conversion uploaded" en pocos minutos).

---

## 4. Cuándo aplican estas conversiones a la subasta

- Aparecen en el panel de Ads en 3-6 horas.
- Smart Bidding empieza a usarlas como señal en ~14 días (necesita masa).
- Recomendable: mantener el snippet GTM y el form sin tocar durante mínimo 30 días antes de tomar decisiones de bid strategy.
