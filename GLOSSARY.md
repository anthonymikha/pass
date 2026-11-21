# PASS

Performance Analytics and Sports Solutions: players book courts at clubs, coaches train players and teams, the money owed for each session is recorded and ticked off at the court, and players log how hard they trained and how they recover.

## People

**Coach**:
A person who offers training and may charge a coach fee for it.

**Shadow player**:
A player with no account of their own, created and looked after by a coach (typically a child). Never signs in.
_Avoid_: managed player, dummy user

**Team coach**:
The coach currently in charge of a team. Only the team coach may follow the team's members.
_Avoid_: team owner, team manager

**Team creator**:
The coach who created a team. A historical fact only: it gives no rights once that coach is no longer the team coach.
_Avoid_: owner

**Hand-over**:
Passing a team, with its team training that has not started yet, from one team coach to another.
_Avoid_: transfer, change of owner

**Play group**:
Friends who play together, run by the person who created it.

**Team**:
A coached group of players, run by its team coach.

**Group manager**:
Whoever runs a group: the creator of a play group, or the team coach of a team.
_Avoid_: owner, admin

**Deleted user**:
An account its owner deleted: deactivated, personal data scrubbed, kept only so sessions, payments and messages others share still make sense. Shown as "Deleted user".
_Avoid_: removed user

**Deactivated account**:
An account a platform admin switched off. Nothing is removed and it can be switched back on. Not the same as a deleted user.

**Coach's players**:
The players a coach may follow: those with an accepted coaching link to the coach, members of teams the coach currently coaches, and the shadow players the coach looks after.

## Sessions

**Session**:
One reserved block of time to play or to train, on a club's court or, for training, at the coach's own venue.

**Booker**:
The person who reserved a session. The booker chooses how each of its fees is paid.

**Session coach**:
The coach running a training session.

**Participant**:
A person on a session's list, whether invited, accepted or declined.

**Attendee**:
An accepted participant who checked in to the session, or was checked in by the booker, the session coach or the club. Only attendees pay a share of a split fee.
_Avoid_: accepted participant (when talking about who pays)

**No-show**:
An accepted participant who did not check in. A no-show owes no share of a split fee.

## Money

**Court fee**:
What the club is owed for a session: the court price, less any reduction, plus approved rentals.

**Coach fee**:
What the session coach charges for a training session.

**Paid in full**:
A fee owed entirely by one person.

**Split**:
A fee divided into equal shares among a session's attendees, never including the session coach.
_Avoid_: shared, divided

**Billing**:
Turning a finished session's fees into payments, once check-in has closed.

**Waive**:
The payee giving up a payment it is owed, typically from someone who did not attend.
_Avoid_: cancel, forgive, refund

**Payment**:
What one person owes for one session to one payee (a club or a coach).
_Avoid_: invoice, bill

**Declared paid**:
The payer's tick on a payment: "I paid". A claim only; the payment stays due until it is received.
_Avoid_: confirmed, settled

**Received**:
The payee's tick on a payment: the money arrived. Only a received payment is **paid**, counts as revenue and carries a platform fee owed.
_Avoid_: confirmed, settled (settled is the platform's cut, done in the admin)
