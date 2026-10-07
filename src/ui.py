"""Colours and small Core Animation helpers shared by the island's drawing code."""
from AppKit import NSColor, NSFont, NSFontDescriptorSystemDesignRounded, NSFontWeightMedium
from Quartz import CASpringAnimation, CATransaction

WHITE = NSColor.whiteColor()
BLACK = NSColor.blackColor()
GRAY = NSColor.colorWithWhite_alpha_(0.60, 1.0)
FAINT = NSColor.colorWithWhite_alpha_(1.0, 0.14)
HOVER = NSColor.colorWithWhite_alpha_(0.24, 1.0)
GREEN = NSColor.systemGreenColor()
ORANGE = NSColor.systemOrangeColor()
PINK = NSColor.systemPinkColor()
YELLOW = NSColor.systemYellowColor()
RED = NSColor.systemRedColor()
BLUE = NSColor.systemBlueColor()
PURPLE = NSColor.systemPurpleColor()


def no_anim(fn):
    """Run fn with implicit layer animations switched off."""
    CATransaction.begin()
    CATransaction.setDisableActions_(True)
    fn()
    CATransaction.commit()


def font(size, weight=NSFontWeightMedium, rounded=False):
    f = NSFont.monospacedDigitSystemFontOfSize_weight_(size, weight)
    if rounded:
        desc = f.fontDescriptor().fontDescriptorWithDesign_(NSFontDescriptorSystemDesignRounded)
        f = (desc and NSFont.fontWithDescriptor_size_(desc, size)) or f
    return f


def spring(key_path, old, new, damping):
    a = CASpringAnimation.animationWithKeyPath_(key_path)
    a.setFromValue_(old)
    a.setToValue_(new)
    a.setMass_(1.0)
    a.setStiffness_(260.0)
    a.setDamping_(damping)
    a.setDuration_(a.settlingDuration())
    return a
