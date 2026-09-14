"""Getting in: which way of asking a host for bytes works, and what that costs.

Separate from the connectors on purpose. A connector knows how to read a Shopify
feed; nothing in it knows or should know whether the bytes arrived over plain HTTP,
a browser-shaped TLS handshake, or a real browser. `Transport` is the seam, and this
package is the shelf of things that satisfy it plus the record of which one to reach
for per brand.
"""
