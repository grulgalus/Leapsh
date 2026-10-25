from leapsh.api import Addon


class PetHat(Addon):
    def on_load(self):
        self.extend("pet_face", self.hat)

    def hat(self, face, level=1, **ctx):
        if level >= 10:
            return "✦" + face + "✦"
        if level >= 5:
            return "♛" + face
        if level >= 3:
            return "♪" + face
