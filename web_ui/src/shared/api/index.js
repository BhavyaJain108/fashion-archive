// One import for call sites that want the old names.
//
// FashionArchiveAPI was a single class holding auth, the archive and
// favourites. It is three modules now; this composes them back into the name
// the pages already use, so splitting the file did not mean touching every
// call in the app on the same commit.
import ApiClient from './client';
import ArchiveEndpoints from './archive';
import SavesEndpoints from './saves';

export class FashionArchiveAPI {}

// Static inheritance by copy: every own property of the three modules lands on
// the facade, so FashionArchiveAPI.getSeasons and .addFavourite keep working.
for (const source of [ApiClient, ArchiveEndpoints, SavesEndpoints]) {
  for (const key of Object.getOwnPropertyNames(source)) {
    if (['length', 'name', 'prototype'].includes(key)) continue;
    Object.defineProperty(
      FashionArchiveAPI, key, Object.getOwnPropertyDescriptor(source, key)
    );
  }
}

// onUnauthorized is assigned by App.js on the facade, but the request helpers
// read it from ApiClient. Keep the two ends pointed at the same slot.
Object.defineProperty(FashionArchiveAPI, 'onUnauthorized', {
  get() { return ApiClient.onUnauthorized; },
  set(fn) { ApiClient.onUnauthorized = fn; },
  configurable: true,
});

export { default as ArchiveAPI } from './brands';
export { ApiClient };
export default FashionArchiveAPI;
