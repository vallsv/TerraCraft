#!/bin/python3

"""
 ________                                        ______                       ______     __
|        \                                      /      \                     /      \   |  \
 \$$$$$$$$______    ______    ______   ______  |  $$$$$$\  ______   ______  |  $$$$$$\ _| $$_
   | $$  /      \  /      \  /      \ |      \ | $$   \$$ /      \ |      \ | $$_  \$$|   $$ \
   | $$ |  $$$$$$\|  $$$$$$\|  $$$$$$\ \$$$$$$\| $$      |  $$$$$$\ \$$$$$$\| $$ \     \$$$$$$
   | $$ | $$    $$| $$   \$$| $$   \$$/      $$| $$   __ | $$   \$$/      $$| $$$$      | $$ __
   | $$ | $$$$$$$$| $$      | $$     |  $$$$$$$| $$__/  \| $$     |  $$$$$$$| $$        | $$|  \
   | $$  \$$     \| $$      | $$      \$$    $$ \$$    $$| $$      \$$    $$| $$         \$$  $$
    \$$   \$$$$$$$ \$$       \$$       \$$$$$$$  \$$$$$$  \$$       \$$$$$$$ \$$          \$$$$


Copyright (C) 2013 Michael Fogleman
Copyright (C) 2018/2019 Stefano Peris <xenonlab.develop@gmail.com>

Github repository: <https://github.com/XenonLab-Studio/TerraCraft>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import time

from collections import deque

from pyglet.gl import *

from .blocks import *
from .utilities import *
from game.utilities import sectorize


class Sector:
    """A chunk of the world

    It contains the block description of a sector. As it is initially generated.
    """

    def __init__(self, position):
        self.blocks = {}
        """Location and kind of the blocks in this sector."""

        self.position = position
        """Location of this sector."""

        self.min_block = [i * SECTOR_SIZE for i in position]
        """Minimum location (included) of block in this section."""

        self.max_block = [(i + 1) * SECTOR_SIZE for i in position]
        """Maximum location (excluded) of block in this section."""

    def contains(self, pos):
        """True if the position `pos` is inside this sector."""
        return (self.min_block[0] <= pos[0] < self.max_block[0]
                and self.min_block[1] <= pos[1] < self.max_block[1]
                and self.min_block[2] <= pos[2] < self.max_block[2])

    def contains_y(self, y):
        """True if the horizontal plan `y` is inside this sector."""
        return self.min_block[1] <= y < self.max_block[1]

    def contains_y_range(self, ymin, ymax):
        """True if the horizontal plan between `ymin` and `ymax` is inside this
        sector."""
        return self.min_block[1] <= ymax and ymin <= self.max_block[1]

    def empty(self, pos):
        """Return false if there is no block at this position in this chunk"""
        return pos not in self.blocks

    def __setitem__(self, pos, value):
        self.blocks[pos] = value

    def __getitem__(self, pos):
        return self.blocks[pos]

    def add_block(self, pos, block):
        """Add a block to this chunk only if the `pos` is part of this chunk."""
        if self.contains(pos):
            self.blocks[pos] = block


class Model(object):
    def __init__(self, batch, group):
        self.batch = batch

        self.group = group

        # A mapping from position to the texture of the block at that position.
        # This defines all the blocks that are currently in the world.
        self.world = {}

        # Procedural generator
        self._generator = None

        # Same mapping as `world` but only contains blocks that are shown.
        self.shown = {}

        # Mapping from position to a pyglet `VertextList` for all shown blocks.
        self._shown = {}

        # Mapping from sector to a list of positions inside that sector.
        self.sectors = {}

        # Actual set of shown sectors
        self.shown_sectors = set({})

        #self.generate_world = generate_world(self) 
        
        # Simple function queue implementation. The queue is populated with
        # _show_block() and _hide_block() calls
        self.queue = deque()

    @property
    def currently_shown(self):
        return len(self._shown)

    @property
    def generator(self):
        return self._generator

    @generator.setter
    def generator(self, generator):
        assert self._generator is None
        generator.set_callback(self.on_sector_received)
        self._generator = generator

    def on_sector_received(self, chunk):
        """Called when a part of the world is returned.

        This is not executed by the main thread. So the result have to be passed
        to the main thread.
        """
        self._enqueue(self.register_sector, chunk)

    def hit_test(self, position, vector, max_distance=NODE_SELECTOR):
        """ Line of sight search from current position. If a block is
        intersected it is returned, along with the block previously in the line
        of sight. If no block is found, return None, None.

        Parameters
        ----------
        position : tuple of len 3
            The (x, y, z) position to check visibility from.
        vector : tuple of len 3
            The line of sight vector.
        max_distance : int
            How many blocks away to search for a hit.

        """
        m = 8
        x, y, z = position
        dx, dy, dz = vector
        previous = None
        for _ in range(max_distance * m):
            checked_position = normalize((x, y, z))
            if checked_position != previous and checked_position in self.world:
                return checked_position, previous
            previous = checked_position
            x, y, z = x + dx / m, y + dy / m, z + dz / m
        return None, None

    def empty(self, position):
        """ Returns True if given `position` does not contain block.
        """
        return not position in self.world

    def exposed(self, position):
        """ Returns False if given `position` is surrounded on all 6 sides by
        blocks, True otherwise.

        """
        x, y, z = position
        for dx, dy, dz in FACES:
            if (x + dx, y + dy, z + dz) not in self.world:
                return True
        return False

    def add_block(self, position, block, immediate=True):
        """ Add a block with the given `texture` and `position` to the world.

        Parameters
        ----------
        position : tuple of len 3
            The (x, y, z) position of the block to add.
        block : Block object
            An instance of the Block class.
        immediate : bool
            Whether or not to draw the block immediately.

        """
        if position in self.world:
            self.remove_block(position, immediate)
        self.world[position] = block
        self.sectors.setdefault(sectorize(position), []).append(position)
        if immediate:
            if self.exposed(position):
                self.show_block(position)
            self.check_neighbors(position)

    def remove_block(self, position, immediate=True):
        """ Remove the block at the given `position`.

        Parameters
        ----------
        position : tuple of len 3
            The (x, y, z) position of the block to remove.
        immediate : bool
            Whether or not to immediately remove block from canvas.

        """
        del self.world[position]
        self.sectors[sectorize(position)].remove(position)
        if immediate:
            if position in self.shown:
                self.hide_block(position)
            self.check_neighbors(position)

    def check_neighbors(self, position):
        """ Check all blocks surrounding `position` and ensure their visual
        state is current. This means hiding blocks that are not exposed and
        ensuring that all exposed blocks are shown. Usually used after a block
        is added or removed.

        """
        x, y, z = position
        for dx, dy, dz in FACES:
            neighbor = (x + dx, y + dy, z + dz)
            if neighbor not in self.world:
                continue
            if self.exposed(neighbor):
                if neighbor not in self.shown:
                    self.show_block(neighbor)
            else:
                if neighbor in self.shown:
                    self.hide_block(neighbor)

    def show_block(self, position, immediate=True):
        """ Show the block at the given `position`. This method assumes the
        block has already been added with add_block()

        Parameters
        ----------
        position : tuple of len 3
            The (x, y, z) position of the block to show.
        immediate : bool
            Whether or not to show the block immediately.

        """
        block = self.world[position]
        self.shown[position] = block
        if immediate:
            self._show_block(position, block)
        else:
            self._enqueue(self._show_block, position, block)

    def _show_block(self, position, block):
        """ Private implementation of the `show_block()` method.

        Parameters
        ----------
        position : tuple of len 3
            The (x, y, z) position of the block to show.
        block : Block instance
            An instance of the Block class

        """
        x, y, z = position
        vertex_data = cube_vertices(x, y, z, 0.5)
        # create vertex list
        # FIXME Maybe `add_indexed()` should be used instead
        self._shown[position] = self.batch.add(24, GL_QUADS, self.group,
                                               ('v3f/static', vertex_data),
                                               ('t2f/static', block.tex_coords))

    def hide_block(self, position, immediate=True):
        """ Hide the block at the given `position`. Hiding does not remove the
        block from the world.

        Parameters
        ----------
        position : tuple of len 3
            The (x, y, z) position of the block to hide.
        immediate : bool
            Whether or not to immediately remove the block from the canvas.

        """
        self.shown.pop(position)
        if immediate:
            self._hide_block(position)
        else:
            self._enqueue(self._hide_block, position)

    def _hide_block(self, position):
        """ Private implementation of the 'hide_block()` method.

        """
        block = self._shown.pop(position, None)
        if block:
            block.delete()

    def register_sector(self, sector):
        """Add a new sector to this world definition.
        """
        # Assert if the sector is already there.
        # It also could be skipped, or merged together.
        assert sector.position not in self.sectors or len(self.sectors[sector.position]) == 0

        shown = sector.position in self.shown_sectors
        for position, block in sector.blocks.items():
            self.add_block(position, block, immediate=False)
            if shown:
                self.show_block(position, immediate=False)

    def show_sector(self, sector):
        """ Ensure all blocks in the given sector that should be shown are
        drawn to the canvas.

        """
        self.shown_sectors.add(sector)

        if sector not in self.sectors:
            if self.generator is not None:
                # This sector is about to be loaded
                self.sectors[sector] = []
                self.generator.request_sector(sector)
                return

        for position in self.sectors.get(sector, []):
            if position not in self.shown and self.exposed(position):
                self.show_block(position, False)

    def hide_sector(self, sector):
        """ Ensure all blocks in the given sector that should be hidden are
        removed from the canvas.

        """
        self.shown_sectors.discard(sector)

        for position in self.sectors.get(sector, []):
            if position in self.shown:
                self.hide_block(position, False)

    def show_only_sectors(self, sectors):
        """ Update the shown sectors.

        Show the ones which are not part of the list, and hide the others.
        """
        after_set = set(sectors)
        before_set = self.shown_sectors
        hide = before_set - after_set
        # Use a list to respect the order of the sectors
        show = [s for s in sectors if s not in before_set]
        for sector in show:
            self.show_sector(sector)
        for sector in hide:
            self.hide_sector(sector)

    def _enqueue(self, func, *args):
        """ Add `func` to the internal queue.

        """
        self.queue.append((func, args))

    def _dequeue(self):
        """ Pop the top function from the internal queue and call it.

        """
        func, args = self.queue.popleft()
        func(*args)

    def process_queue(self):
        """ Process the entire queue while taking periodic breaks. This allows
        the game loop to run smoothly. The queue contains calls to
        _show_block() and _hide_block() so this method should be called if
        add_block() or remove_block() was called with immediate=False

        """
        start = time.perf_counter()
        while self.queue and time.perf_counter() - start < 1.0 / TICKS_PER_SEC:
            self._dequeue()

    def process_entire_queue(self):
        """ Process the entire queue with no breaks.

        """
        while self.queue:
            self._dequeue()
