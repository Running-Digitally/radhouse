"use strict";
(() => {
  const root = "/workspace-assets/agent-profile/echo/";
  const clips = ["a-curious.mp4", "b-thoughtful.mp4", "c-playful.mp4"];
  const portraits = new WeakMap();

  class EchoPortrait {
    constructor(image) {
      this.image = image;
      this.motion = matchMedia("(prefers-reduced-motion: reduce)");
      this.enabled = true;
      this.visible = false;
      this.failed = false;
      this.bag = [];
      this.last = null;
      this.epoch = 0;
      this.timer = null;
      this.timeout = null;
      this.frame = null;
      this.wrapper = document.createElement("span");
      this.wrapper.className = "rh-animated-portrait";
      image.before(this.wrapper);
      this.wrapper.append(image);
      image.src = root + "neutral.png";
      this.video = document.createElement("video");
      this.video.muted = true;
      this.video.playsInline = true;
      this.video.preload = "none";
      this.video.hidden = true;
      this.video.setAttribute("aria-hidden", "true");
      this.video.tabIndex = -1;
      this.wrapper.append(this.video);
      this.sync = () => this.canRun() ? this.wait() : this.stop();
      this.ended = () => { this.neutral(); this.wait(); };
      this.error = () => { this.failed = true; this.stop(); };
      this.video.addEventListener("ended", this.ended);
      this.video.addEventListener("error", this.error);
      this.motion.addEventListener("change", this.sync);
      document.addEventListener("visibilitychange", this.sync);
      this.observer = new IntersectionObserver(entries => {
        this.visible = entries[0].isIntersecting;
        this.sync();
      });
      this.observer.observe(this.wrapper);
    }

    canRun() {
      return this.enabled && !this.failed && !this.motion.matches && !document.hidden
        && this.visible && this.wrapper.isConnected;
    }

    nextClip() {
      if (!this.bag.length) {
        this.bag = [...clips];
        for (let i = this.bag.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          [this.bag[i], this.bag[j]] = [this.bag[j], this.bag[i]];
        }
        if (this.bag[0] === this.last) [this.bag[0], this.bag[1]] = [this.bag[1], this.bag[0]];
      }
      return this.bag.shift();
    }

    wait() {
      if (!this.canRun() || this.timer !== null || this.playing) return;
      // Start the rest interval only after the preceding clip has ended.
      this.timer = setTimeout(() => { this.timer = null; void this.play(); }, 2000 + Math.random() * 4000);
    }

    async play() {
      if (!this.canRun()) return;
      this.playing = true;
      const epoch = ++this.epoch;
      const clip = this.nextClip();
      this.last = clip;
      this.video.src = root + clip;
      this.timeout = setTimeout(this.error, 15000);
      try {
        // Keep the neutral image visible until an actual decoded frame is ready.
        const reveal = () => {
          this.frame = null;
          if (epoch === this.epoch && this.canRun()) this.video.hidden = false;
        };
        if (this.video.requestVideoFrameCallback) this.frame = this.video.requestVideoFrameCallback(reveal);
        await this.video.play();
        if (epoch !== this.epoch) return;
        clearTimeout(this.timeout); this.timeout = null;
        if (!this.canRun()) { this.stop(); return; }
        if (!this.video.requestVideoFrameCallback) reveal();
      } catch (_) {
        if (epoch === this.epoch) this.error();
      }
    }

    neutral() {
      this.epoch++;
      clearTimeout(this.timeout); this.timeout = null;
      if (this.frame !== null) this.video.cancelVideoFrameCallback?.(this.frame);
      this.frame = null;
      this.video.pause();
      this.video.hidden = true;
      this.playing = false;
    }

    stop() {
      clearTimeout(this.timer); this.timer = null;
      this.neutral();
      // Release the decoder when motion is off or this portrait is out of view.
      this.video.removeAttribute("src");
      this.video.load();
    }

    update(enabled) { this.image.src = root + "neutral.png"; this.enabled = enabled; this.sync(); }

    destroy() {
      this.observer.disconnect();
      this.motion.removeEventListener("change", this.sync);
      document.removeEventListener("visibilitychange", this.sync);
      this.video.removeEventListener("error", this.error);
      this.video.removeEventListener("ended", this.ended);
      this.stop();
      this.wrapper.replaceWith(this.image);
    }
  }

  window.RadhousePortrait = Object.freeze({
    update(image, profile, entry) {
      let player = portraits.get(image);
      if (entry?.id !== "echo") {
        if (player) { player.destroy(); portraits.delete(image); }
        return;
      }
      if (!player) { player = new EchoPortrait(image); portraits.set(image, player); }
      // The existing saved motion preference governs the portrait as well.
      player.update(profile?.stateMotion !== false);
    },
    clear(image) { const player = portraits.get(image); if (player) { player.destroy(); portraits.delete(image); } },
  });
})();
