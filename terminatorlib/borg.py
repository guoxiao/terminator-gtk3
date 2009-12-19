#!/usr/bin/python
# Terminator by Chris Jones <cmsj@tenshu.net>
# GPL v2 only
"""borg.py - We are the borg. Resistance is futile.
   http://code.activestate.com/recipes/66531/
   ActiveState's policy appears to be that snippets
   exist to encourage re-use, but I can not find any
   specific licencing terms.

>>> obj1 = TestBorg()
>>> obj2 = TestBorg()
>>> obj1.attribute
0
>>> obj2.attribute
0
>>> obj1.attribute = 12345
>>> obj1.attribute
12345
>>> obj2.attribute
12345
>>> obj2.attribute = 54321
>>> obj1.attribute
54321
"""

# pylint: disable-msg=R0903
# pylint: disable-msg=R0921
class Borg:
    """Definition of a class that can never be duplicated. Correct usage is
    thus:
        
        from borg import Borg
        class foo(Borg):
            # All attributes on a borg class *must* = None
            attribute = None

            def __init__(self):
                Borg.__init__(self)

            def prepare_attributes(self):
                if not self.attribute:
                    self.attribute = []

        bar = foo()
        bar.prepare_attributes()
    
    The important thing to note is that all attributes of borg classes *must* be
    declared as being None. If you attempt to use static class attributes you
    will get unpredicted behaviour. Instead, prepare_attributes() must be called
    which will then see the attributes in the shared state, and initialise them
    if necessary."""
    __shared_state = {} 

    def __init__(self):
        """Class initialiser. Overwrite our class dictionary with the shared
        state. This makes us identical to every other instance of this class
        type."""
        self.__dict__ = self.__shared_state

    def prepare_attributes(self):
        """This should be used to prepare any attributes of the borg class."""
        raise NotImplementedError('prepare_attributes')

if __name__ == '__main__':
    class TestBorg(Borg):
        attribute = None

        def __init__(self):
            Borg.__init__(self)
            self.prepare_attributes()
        
        def prepare_attributes(self):
            if not self.attribute:
                self.attribute = 0

    import doctest
    (failed, attempted) = doctest.testmod()
    print "%d/%d tests failed" % (failed, attempted)

