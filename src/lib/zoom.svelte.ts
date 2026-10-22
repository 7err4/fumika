// Full-size view of page versions / assets (user 21 Oct: the previews are too small). One shared lightbox, mounted in App.svelte.
type Pick = ((k: number) => void) | null;
type Remove = ((k: number) => string[]) | null;
export const zoom = $state({ images: [] as string[], at: 0, pick: null as Pick, picked: -1, remove: null as Remove });

/** open the lightbox on `images` at `at`. Optional: `pick` adds "use this version" (`picked` = the current choice),
 *  `remove` adds "remove version" and returns the images that are left */
export function openZoom(images: string[], at = 0, pick: Pick = null, picked = -1, remove: Remove = null) {
  if (!images.length) return;
  Object.assign(zoom, { images, at: Math.max(0, Math.min(at, images.length - 1)), pick, picked, remove });
}

export function closeZoom() { zoom.images = []; zoom.pick = null; zoom.remove = null; }
