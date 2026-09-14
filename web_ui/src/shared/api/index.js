// One import for call sites that want the old names.
//
// FashionArchiveAPI was a single class holding auth, the archive and
// favourites. It is three modules now; this composes them back into the name
// the pages already use, so splitting the file did not mean touching every
// call in the app on the same commit.
import ApiClient from './client';
import AlbumsEndpoints from './albums';
import ArchiveEndpoints from './archive';
import SavesEndpoints from './saves';

export class FashionArchiveAPI {}

// Static inheritance by copy: every own property of one module lands on
// `target`. Exported so a test can exercise the collision guard directly
// without having to force a real collision between the three live modules.
//
// A name collision here is a programming error, not a runtime condition: two
// modules exporting the same static name would mean one silently shadows the
// other with no error, and the wrong endpoint gets called. Better to crash at
// startup than to run with the wrong function bound to a name.
export function copyStatics(target, source) {
  for (const key of Object.getOwnPropertyNames(source)) {
    if (['length', 'name', 'prototype'].includes(key)) continue;
    if (Object.prototype.hasOwnProperty.call(target, key)) {
      throw new Error(
        `API facade collision: '${key}' is already defined on the facade `
        + `(copying from ${source.name || source})`
      );
    }
    Object.defineProperty(
      target, key, Object.getOwnPropertyDescriptor(source, key)
    );
  }
}

// FashionArchiveAPI.getSeasons and .addFavourite keep working because every
// own property of the three modules lands on the facade here.
for (const source of [ApiClient, AlbumsEndpoints, ArchiveEndpoints, SavesEndpoints]) {
  copyStatics(FashionArchiveAPI, source);
}

// onUnauthorized is assigned by App.js on the facade, but the request helpers
// read it from ApiClient. Keep the two ends pointed at the same slot.
Object.defineProperty(FashionArchiveAPI, 'onUnauthorized', {
  get() { return ApiClient.onUnauthorized; },
  set(fn) { ApiClient.onUnauthorized = fn; },
  configurable: true,
});

export { default as AlbumsAPI } from './albums';
export { default as ArchiveAPI } from './brands';
export { ApiClient };
export default FashionArchiveAPI;
