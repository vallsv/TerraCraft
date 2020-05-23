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


def iter_neighbors(position):
    """Iterate all the positions neighboring this position"""
    x, y, z = position
    for face in FACES:
        dx, dy, dz = face
        neighbor = x + dx, y + dy, z + dz
        yield neighbor, face


class Sector:
    """A sector is a chunk of the world of the size SECTOR_SIZE in each directions.

    It contains the block description of a sector. As it is initially generated.
    """

    def __init__(self, position):
        self.blocks = {}
        """Location and kind of the blocks in this sector."""

        self.visible = set({})
        """Set of visible blocks if we look at this sector alone"""

        self.outline = set({})
        """Blocks on the outline of the section"""

        self.face_full_cache = set({})

        self.position = position
        """Location of this sector."""

        self.min_block = [i * SECTOR_SIZE for i in position]
        """Minimum location (included) of block in this section."""

        self.max_block = [(i + 1) * SECTOR_SIZE for i in position]
        """Maximum location (excluded) of block in this section."""

    def is_face_full(self, direction):
        """Check if one of the face of this section is full of blocks.

        The direction is a normalized vector from `FACES`."""
        return direction in self.face_full_cache

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

    def blocks_from_face(self, face):
        """Iterate all blocks from a face"""
        axis = 0 if face[0] != 0 else (1 if face[1] != 0 else 2)
        if face[axis] == -1:
            pos = self.min_block[axis]
        else:
            pos = self.max_block[axis] - 1
        for block in self.outline:
            if block[axis] == pos:
                yield block

    def empty(self, pos):
        """Return false if there is no block at this position in this chunk"""
        return pos not in self.blocks

    def add_block(self, position, block):
        """Add a block to this chunk only if the `position` is part of this chunk."""
        if not self.contains(position):
            return

        self.blocks[position] = block
        if self.exposed(position):
            self.visible.add(position)
        self.check_neighbors(position)

        for axis in range(3):
            if position[axis] == self.min_block[axis]:
                self.outline.add(position)
                face = [0] * 3
                face[axis] = -1
                face = tuple(face)
                if self.check_face_full(face):
                    self.face_full_cache.add(face)
            elif position[axis] == self.max_block[axis] - 1:
                self.outline.add(position)
                face = [0] * 3
                face[axis] = 1
                face = tuple(face)
                if self.check_face_full(face):
                    self.face_full_cache.add(face)

    def check_face_full(self, face):
        axis = (face[1] != 0) * 1 + (face[2] != 0) * 2
        if face[axis] == -1:
            fixed_pos = self.min_block[axis]
        else:
            fixed_pos = self.max_block[axis] - 1
        axis2 = (axis + 1) % 3
        axis3 = (axis + 2) % 3

        pos = [None] * 3
        pos[axis] = fixed_pos
        for a2 in range(self.min_block[axis2], self.max_block[axis2]):
            for a3 in range(self.min_block[axis3], self.max_block[axis3]):
                pos[axis2] = a2
                pos[axis3] = a3
                block_pos = tuple(pos)
                if block_pos not in self.blocks:
                    return False
        return True

    def remove_block(self, position):
        """Remove a block from this sector at the `position`.

        Returns discarded full faces in case.
        """
        del self.blocks[position]
        self.check_neighbors(position)
        self.visible.discard(position)
        self.outline.discard(position)

        discarded = set({})
        # Update the full faces
        for face in list(self.face_full_cache):
            axis = (face[1] != 0) * 1 + (face[2] != 0) * 2
            if face[axis] == -1:
                border = self.min_block
            else:
                x, y, z = self.max_block
                border = x - 1, y - 1, z - 1
            if position[axis] == border[axis]:
                self.face_full_cache.discard(face)
                discarded.add(face)
        return discarded

    def exposed(self, position):
        """ Returns False if given `position` is surrounded on all 6 sides by
        blocks, True otherwise.
        """
        for neighbor, _face in iter_neighbors(position):
            if self.empty(neighbor):
                return True
        return False

    def check_neighbors(self, position):
        """ Check all blocks surrounding `position` and ensure their visual
        state is current. This means hiding blocks that are not exposed and
        ensuring that all exposed blocks are shown. Usually used after a block
        is added or removed.
        """
        for neighbor, _face in iter_neighbors(position):
            if self.empty(neighbor):
                continue
            if self.exposed(neighbor):
                if neighbor not in self.visible:
                    self.visible.add(neighbor)
            else:
                if neighbor in self.visible:
                    self.visible.remove(neighbor)


class Model(object):
    def __init__(self, batch, group):
        self.batch = batch

        self.group = group

        # Procedural generator
        self._generator = None

        # Same mapping as `world` but only contains blocks that are shown.
        self.shown = {}

        # Mapping from position to a pyglet `VertextList` for all shown blocks.
        self._shown = {}

        # Mapping from sector index a list of positions inside that sector.
        self.sectors = {}

        # Actual set of shown sectors
        self.shown_sectors = set({})

        # List of sectors requested but not yet received
        self.requested = set({})

        # Simple function queue implementation. The queue is populated with
        # _show_block() and _hide_block() calls
        self.queue = deque()

    @property
    def currently_shown(self):
        return len(self._shown)

    def count_blocks(self):
        """Return the number of blocks in this model"""
        return sum([len(s.blocks) for s in self.sectors.values() if s is not None])

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
            if checked_position != previous and not self.empty(checked_position):
                return checked_position, previous
            previous = checked_position
            x, y, z = x + dx / m, y + dy / m, z + dz / m
        return None, None

    def empty(self, position, must_be_loaded=False):
        """ Returns True if given `position` does not contain block.

        If `must_be_loaded` is True, this returns False if the block is not yet loaded.
        """
        sector_pos = sectorize(position)
        sector = self.sectors.get(sector_pos, None)
        if sector is None:
            return not must_be_loaded
        return sector.empty(position)

    def exposed(self, position):
        """ Returns False if given `position` is surrounded on all 6 sides by
        blocks, True otherwise.

        """
        x, y, z = position
        for dx, dy, dz in FACES:
            pos = (x + dx, y + dy, z + dz)
            if self.empty(pos, must_be_loaded=True):
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
        sector_pos = sectorize(position)
        sector = self.sectors.get(sector_pos)
        if sector is None:
            # Sector not yet loaded
            # It would be better to create it
            # and then to merge it when the sector is loaded
            return

        if position in sector.blocks:
            self.remove_block(position, immediate)
        sector.add_block(position, block)
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
        sector_pos = sectorize(position)
        sector = self.sectors.get(sector_pos)
        if sector is None:
            # Nothing to do
            return

        if position not in sector.blocks:
            # Nothing to do
            return


        discarded = sector.remove_block(position)

        # Removing a block can make a neighbor section visible
        if discarded:
            x, y, z = sector.position
            for dx, dy, dz in discarded:
                neighbor_pos = x + dx, y + dy, z + dz
                if neighbor_pos in self.sectors:
                    continue
                if neighbor_pos in self.requested:
                    continue
                if neighbor_pos not in self.shown_sectors:
                    continue
                neighbor = self.generator.generate(neighbor_pos)
                self.register_sector(neighbor)

        if immediate:
            if position in self.shown:
                self.hide_block(position)
            self.check_neighbors(position)

    def get_block(self, position):
        """Return a block from this position.

        If no blocks, None is returned.
        """
        sector_pos = sectorize(position)
        sector = self.sectors.get(sector_pos)
        if sector is None:
            return None
        return sector.blocks.get(position, None)

    def check_neighbors(self, position):
        """ Check all blocks surrounding `position` and ensure their visual
        state is current. This means hiding blocks that are not exposed and
        ensuring that all exposed blocks are shown. Usually used after a block
        is added or removed.
        """
        x, y, z = position
        for dx, dy, dz in FACES:
            neighbor = (x + dx, y + dy, z + dz)
            if self.empty(neighbor):
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
        block = self.get_block(position)
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
        assert sector.position not in self.sectors
        self.requested.discard(sector.position)
        self.sectors[sector.position] = sector
        if sector.position not in self.shown_sectors:
            return

        to_show = set([])

        # Update the displayed blocks
        for position in sector.visible:
            if position not in sector.outline or self.exposed(position):
                to_show.add(position)

        # Check neighbor block which was not displayed
        for neighbor_pos, face in iter_neighbors(sector.position):
            if sector.is_face_full(face):
                continue
            neighbor = self.sectors.get(neighbor_pos, None)
            if neighbor:
                opposite = -face[0], -face[1], -face[2]
                for position in neighbor.blocks_from_face(opposite):
                    if position not in self.shown:
                        x, y, z = position
                        check = x - face[0], y - face[1], z - face[2]
                        if sector.empty(check):
                            to_show.add(position)

        for position in to_show:
            self.show_block(position, immediate=False)

        # Is sector around have to be loaded too?
        x, y, z = sector.position
        for face in FACES:
            # The sector have to be accessible
            if sector.is_face_full(face):
                continue
            pos = x + face[0], y + face[1], z + face[2]
            # Must not be already loaded
            if pos in self.sectors:
                continue
            # Must be shown actually
            if pos not in self.shown_sectors:
                continue
            # Must not be already requested
            if pos in self.requested:
                continue
            # Then request the sector
            if self.generator is not None:
                self.requested.add(pos)
                self.generator.request_sector(pos)

    def show_sector(self, sector_pos):
        """ Ensure all blocks in the given sector that should be shown are
        drawn to the canvas.
        """
        self.shown_sectors.add(sector_pos)
        if sector_pos not in self.sectors:
            if sector_pos in self.requested:
                # Already requested
                return
            # If sectors around not yet loaded
            if not self.is_sector_visible(sector_pos):
                return
            if self.generator is not None:
                # This sector is about to be loaded
                self.requested.add(sector_pos)
                self.generator.request_sector(sector_pos)
                return

        sector = self.sectors.get(sector_pos, None)
        if sector:
            for position in sector.visible:
                if position not in self.shown:
                    if position in sector.outline:
                        if self.exposed(position):
                            self.show_block(position, False)
                    else:
                        self.show_block(position, False)

    def is_sector_visible(self, sector_pos):
        """Check if a sector is visible.

        For now only check if no from a sector position.
        """
        x, y, z = sector_pos
        for dx, dy, dz in FACES:
            pos = (x + dx, y + dy, z + dz)
            neighbor = self.sectors.get(pos, None)
            if neighbor is not None:
                neighbor_face = (-dx, -dy, -dz)
                if not neighbor.is_face_full(neighbor_face):
                    return True
        return False

    def hide_sector(self, sector_pos):
        """ Ensure all blocks in the given sector that should be hidden are
        removed from the canvas.

        """
        self.shown_sectors.discard(sector_pos)

        sector = self.sectors.get(sector_pos, None)
        if sector:
            for position in sector.blocks.keys():
                if position in self.shown:
                    self.hide_block(position, False)

    def show_only_sectors(self, sector_positions):
        """ Update the shown sectors.

        Show the ones which are not part of the list, and hide the others.
        """
        after_set = set(sector_positions)
        before_set = self.shown_sectors
        hide = before_set - after_set
        # Use a list to respect the order of the sectors
        show = [s for s in sector_positions if s not in before_set]
        for sector_pos in show:
            self.show_sector(sector_pos)
        for sector_pos in hide:
            self.hide_sector(sector_pos)

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
