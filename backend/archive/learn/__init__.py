"""The learning loop: the seven steps a person took by hand, as the system's own work.

Measure → classify the wall → look at one page → write the narrowest rule → verify on
the brands that did not teach it → write it down → measure again. Each module here is
one of those steps, and the dossier is where all of them write.

    signature   what kind of shop this is, in a few words — the key rules hang on
    dossier     everything known about one brand, unbounded, dated
    walls       what stands between us and the products, and what to do about it
    meter       what a brand costs, in the units the walls are priced in
    budget      the fleet's ceiling, and the two pools under it
    recipes     a lane described as data, so the model can propose one without code
    gate        no proposal lands without proof on its brand and on its neighbours
    analyst     the model, at the three places a rule cannot be written by a rule
    loop        the tick that walks the fleet and does the mechanical part unattended
"""
