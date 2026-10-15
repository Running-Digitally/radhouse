"use strict";
// Presentation-only character data, shared by the documentation mock and future UI consumers.
window.RadhouseCharacters = (() => {
  const themes = [
  {
    "id": "hearthside",
    "name": "Hearthside",
    "style": "Woodland storybook",
    "description": "Tactile woodland companions, warm knits and a light in the window.",
    "cover": "ember"
  },
  {
    "id": "kiln",
    "name": "Kiln Club",
    "style": "Handmade ceramics",
    "description": "Little stoneware spirits, pooled glazes and the charm of things made by hand.",
    "cover": "miro"
  },
  {
    "id": "paper",
    "name": "Paper Trails",
    "style": "Cut-paper adventurers",
    "description": "Layered paper people with a knack for making, mapping and finding a way.",
    "cover": "rue"
  },
  {
    "id": "signal",
    "name": "Signal Station",
    "style": "Retro-future explorers",
    "description": "Brass, enamel and a little cosmic curiosity. Friendly faces from the next frontier.",
    "cover": "beacon"
  }
];
  const profiles = [
  {
    "id": "ember",
    "name": "Ember",
    "theme": "hearthside",
    "role": "The host",
    "story": "Once the keeper of a tiny hillside inn. Now keeps the light on while you find your next good idea.",
    "intro": "Keeps the light on while you find your next good idea.",
    "reply": "Of course. Let’s put the kettle on and start with what matters."
  },
  {
    "id": "moss",
    "name": "Moss",
    "theme": "hearthside",
    "role": "The archivist",
    "story": "A collector of overlooked details and well-thumbed notebooks. Believes good ideas grow with a little patience.",
    "intro": "Good ideas grow with a little patience.",
    "reply": "Let’s look a little closer. There’s usually something useful hiding in the details."
  },
  {
    "id": "aster",
    "name": "Aster",
    "theme": "hearthside",
    "role": "The navigator",
    "story": "A quiet navigator with a sky full of questions. Turns faraway possibilities into a next step you can take.",
    "intro": "Faraway possibilities. A next step you can take.",
    "reply": "Absolutely. Let’s map what we know, then find a promising direction."
  },
  {
    "id": "lumi",
    "name": "Lumi",
    "theme": "hearthside",
    "role": "The storyteller",
    "story": "A moonlit storyteller who sees connections others miss. Makes a little room for the unexpected.",
    "intro": "Makes a little room for the unexpected.",
    "reply": "Yes. Let’s follow the interesting thread and see what it brings into view."
  },
  {
    "id": "miro",
    "name": "Miro",
    "theme": "kiln",
    "role": "The maker",
    "story": "Born beside a potter’s warm kiln, with a leaf for a lucky charm. Finds a useful shape for ideas that are still a little soft.",
    "intro": "A useful shape for your next idea.",
    "reply": "Let’s work with what we have. A small first shape gives us something to build on."
  },
  {
    "id": "nori",
    "name": "Nori",
    "theme": "kiln",
    "role": "The gardener",
    "story": "A sea-glass spirit who tends a windowsill garden. Notices what needs care before it asks.",
    "intro": "A little care goes a long way.",
    "reply": "Let’s give this a little attention. We can make room for the part that needs it most."
  },
  {
    "id": "pebble",
    "name": "Pebble",
    "theme": "kiln",
    "role": "The steady hand",
    "story": "Smoothed by a thousand quiet river mornings. Patient with tangled plans and very good at one thing at a time.",
    "intro": "One thing at a time. We’ll get there.",
    "reply": "We can untangle this. Let’s take the first knot, then the next."
  },
  {
    "id": "rue",
    "name": "Rue",
    "theme": "paper",
    "role": "The pathfinder",
    "story": "A courier who knows every shortcut through the paper city. Carries good questions wherever they need to go.",
    "intro": "There’s always another way through.",
    "reply": "Let’s find a way through. What’s the destination, and what’s blocking the path?"
  },
  {
    "id": "kit",
    "name": "Kit",
    "theme": "paper",
    "role": "The inventor",
    "story": "Keeps a workshop full of promising offcuts and half-finished wonders. Can usually make something work with one more fold.",
    "intro": "Every good idea starts with an offcut.",
    "reply": "Let’s see what we can make from this. There may be a simpler mechanism hiding in plain sight."
  },
  {
    "id": "sol",
    "name": "Sol",
    "theme": "paper",
    "role": "The cartographer",
    "story": "Maps places that haven’t quite been imagined yet. Leaves enough blank space for a happy detour.",
    "intro": "A clear direction. Room for a detour.",
    "reply": "Let’s sketch the territory together. We can mark what’s certain and leave room for a surprise."
  },
  {
    "id": "beacon",
    "name": "Beacon",
    "theme": "signal",
    "role": "The keeper",
    "story": "Tends the welcome light on a quiet orbital station. Makes unfamiliar territory feel like somewhere you belong.",
    "intro": "A familiar light in unfamiliar territory.",
    "reply": "You’ve got a signal. Let’s get our bearings and take the next step together."
  },
  {
    "id": "echo",
    "name": "Echo",
    "theme": "signal",
    "role": "The listener",
    "story": "An old radio operator with a talent for hearing the useful bit through the static. Keeps a dry joke on the spare channel.",
    "intro": "Good questions come through clearly.",
    "reply": "I’m listening. Let’s tune out the noise and find the part worth following."
  },
  {
    "id": "orbit",
    "name": "Orbit",
    "theme": "signal",
    "role": "The explorer",
    "story": "Collects star charts and improbable routes home. Turns big possibilities into a course you can actually follow.",
    "intro": "Big possibilities. A course you can follow.",
    "reply": "Let’s plot a course. We can start close to home and see how far the idea takes us."
  }
];
  return Object.freeze({themes:Object.freeze(themes.map(Object.freeze)),profiles:Object.freeze(profiles.map(Object.freeze))});
})();
